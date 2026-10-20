"""Database QA of a reference data release (stage ``database``), run in PostGIS before publication.

The pipeline checks each file before it is loaded (``app.pipeline.file_qa``); these checks look at the
release as the API will see it: every layer, every dataset, the relations between them, and their
lineage. Findings are stored in ``meta.qa_finding`` under a ``meta.qa_run``; the run records the release's
content fingerprint, and the database refuses to publish a release whose latest run did not see its final
content or left errors nobody waived (migration 20260924_0008).

Checks (``CHECKS`` below lists them with their severities):

* **release and lineage**: loads that did not complete, missing metadata (accuracy, version, source
  reference), layers without data;
* **licences**: rejected or (for production) unreviewed licences, restricted licences without
  permission (WDPA, non-commercial or no-derivatives terms), share-alike and no-redistribution
  obligations, placeholder data in a production release;
* **CRS**: storage SRID of every geometry (``ST_SRID``) and its metric twin, layers combining sources in
  different CRSs;
* **geometry**: ``ST_IsValid`` / ``ST_IsValidReason`` / ``ST_IsValidDetail`` on every row; repairs made on
  load (``ST_MakeValid``, logged in ``meta.geometry_repair``) rated by how far they moved the boundary
  (``ST_HausdorffDistance``) and changed the area; degenerate, sliver, over-complex and spiky geometry;
* **duplicates**: identical geometries (``ST_Normalize``), point features with the same name and type
  close together, overlapping area features that are almost the same;
* **identifiers**: missing source ids, admin codes that do not match the expected pattern, unnamed
  features;
* **outliers**: features outside the country outline, outside the expected extent, datasets covering too
  little of it, feature counts outside the expected range or far from the current release, areas outside
  the expected range, too many rejected features;
* **topology**: admin areas not inside their parent, overlapping siblings, parents not covered by their
  children, settlements not linked to an admin area.

Every statement is parameterised; table and column names come from the constants in this module.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.errors import GisError
from app.schemas.reference_data import WGS84_CRS, QaExpectations, Severity

logger = logging.getLogger(__name__)

MAX_FINDINGS_PER_CHECK: Final = 100
NOT_RECORDED_PREFIX: Final = "not recorded"
# Licence identifiers whose terms forbid what this platform does (commercial use, redistribution through
# web services, derived data) unless the licensor has granted it in writing.
RESTRICTED_LICENCE: Final = re.compile(
    r"(WDPA|WDPCA|UNEP-WCMC|-NC(-|$)|-ND(-|$)|NonCommercial|NoDeriv)", re.I
)
DEGREES_PER_METRE: Final = 1 / 111_320.0

QaRunStatus = Literal["passed", "warnings", "failed"]


class ReleaseQaError(GisError):
    status_code = 409
    code = "release_qa_failed"
    title = "Reference data release did not pass QA"


@dataclass(frozen=True, slots=True)
class CheckDefinition:
    code: str
    summary: str
    waivable: bool = True


CHECKS: Final[tuple[CheckDefinition, ...]] = (
    CheckDefinition("release.empty", "The release has no datasets (warning)."),
    CheckDefinition("release.load_incomplete", "A dataset load did not complete (error).", waivable=False),
    CheckDefinition("release.layer_missing", "A reference layer has no data (info; warning for production)."),
    CheckDefinition("metadata.accuracy_missing", "Dataset without nominal accuracy (error)."),
    CheckDefinition("metadata.version_missing", "Dataset without source version (warning)."),
    CheckDefinition("metadata.source_not_recorded", "Dataset without source URL or reference (warning)."),
    CheckDefinition(
        "metadata.retrieval_missing", "Dataset without retrieval time or original checksum (info)."
    ),
    CheckDefinition("licence.rejected", "Source whose licence review was rejected (error).", waivable=False),
    CheckDefinition(
        "licence.unreviewed",
        "Source licence not approved (error in production releases, info otherwise).",
        waivable=False,
    ),
    CheckDefinition(
        "licence.restricted",
        "Restricted licence (WDPA, non-commercial, no-derivatives) without written permission (error).",
        waivable=False,
    ),
    CheckDefinition("licence.share_alike", "Share-alike obligations apply (info)."),
    CheckDefinition("licence.no_redistribution", "Data may not leave the platform; exports refused (info)."),
    CheckDefinition(
        "content.synthetic",
        "Synthetic or placeholder features (error in production releases, info otherwise).",
        waivable=False,
    ),
    CheckDefinition("crs.storage_srid", "Geometry not stored in EPSG:4326 (error).", waivable=False),
    CheckDefinition("crs.metric_srid", "Metric twin not in EPSG:5235 (error).", waivable=False),
    CheckDefinition("crs.mixed_sources", "A layer combines sources in different CRSs (warning)."),
    CheckDefinition("geometry.invalid", "ST_IsValid is false (error).", waivable=False),
    CheckDefinition(
        "geometry.repaired", "Polygon repaired on load (info, warning or error by boundary shift)."
    ),
    CheckDefinition("geometry.degenerate", "Polygon or line smaller than the minimum (warning)."),
    CheckDefinition("geometry.sliver", "Very thin small polygon (warning)."),
    CheckDefinition("geometry.complexity", "More vertices than expected (warning)."),
    CheckDefinition("geometry.spike", "Line segment longer than expected (warning)."),
    CheckDefinition(
        "duplicate.geometry", "Identical geometries in a layer (warning; error for admin areas)."
    ),
    CheckDefinition("duplicate.near", "Same name and type within the duplicate distance (warning)."),
    CheckDefinition("duplicate.overlap", "Two area features that are almost the same (warning)."),
    CheckDefinition("identifier.missing", "Feature without a source identifier (error)."),
    CheckDefinition("identifier.code_format", "Admin code does not match the expected pattern (warning)."),
    CheckDefinition("identifier.name_missing", "Unnamed features (info)."),
    CheckDefinition(
        "outlier.outside_country", "Feature beyond the country outline and coastal buffer (warning)."
    ),
    CheckDefinition("outlier.extent", "Feature outside the expected extent (error)."),
    CheckDefinition(
        "outlier.coverage", "Dataset covers less of the expected extent than required (warning)."
    ),
    CheckDefinition("outlier.area", "Polygon area outside the expected range (warning)."),
    CheckDefinition("outlier.count", "Feature count outside the expected range (error)."),
    CheckDefinition("outlier.count_change", "Feature count far from the current release (warning)."),
    CheckDefinition("outlier.rejected", "Features rejected on load (info; error above the allowed share)."),
    CheckDefinition("topology.admin_parent", "Admin area not inside its parent (warning; error below half)."),
    CheckDefinition(
        "topology.admin_overlap", "Admin areas of one level overlap (warning; error above ratio)."
    ),
    CheckDefinition("topology.admin_gap", "Parent not covered by its children (warning)."),
    CheckDefinition("topology.settlement_unlinked", "Settlement not linked to an admin area (warning)."),
    CheckDefinition(
        "artifact.sources_missing", "Release artifact without recorded sources (error).", waivable=False
    ),
)
WAIVABLE: Final[Mapping[str, bool]] = {check.code: check.waivable for check in CHECKS}


@dataclass(frozen=True, slots=True)
class ReferenceTable:
    layer: str
    table: str
    kind: Literal["area", "line", "point", "mixed"]


TABLES: Final[tuple[ReferenceTable, ...]] = (
    ReferenceTable("ref.admin_area", "ref.admin_area", "area"),
    ReferenceTable("ref.settlement", "ref.settlement", "mixed"),
    ReferenceTable("ref.facility", "ref.facility", "point"),
    ReferenceTable("ref.road", "ref.road", "line"),
    ReferenceTable("ref.water_body", "ref.water_body", "mixed"),
    ReferenceTable("ref.protected_area", "ref.protected_area", "area"),
    ReferenceTable("ref.risk_zone", "ref.risk_zone", "area"),
)
TABLE_BY_LAYER: Final = {table.layer: table for table in TABLES}

# Layer defaults for expectations a dataset does not state (QaExpectations fields, by name).
LAYER_DEFAULTS: Final[Mapping[str, Mapping[str, Any]]] = {
    "ref.admin_area": {"min_area_m2": 10_000.0},
    "ref.settlement": {"duplicate_distance_m": 200.0},
    "ref.facility": {"duplicate_distance_m": 50.0},
    "ref.road": {"max_segment_m": 25_000.0},
    "ref.water_body": {"max_segment_m": 25_000.0, "min_area_m2": 10.0},
    "ref.protected_area": {"min_area_m2": 100.0},
    "ref.risk_zone": {"min_area_m2": 100.0},
}


@dataclass(frozen=True, slots=True)
class Finding:
    check: str
    severity: Severity
    message: str
    layer: str | None = None
    load_id: uuid.UUID | None = None
    feature_id: uuid.UUID | None = None
    source_feature_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    location_wkb: bytes | None = None


@dataclass(frozen=True, slots=True)
class LoadInfo:
    id: uuid.UUID
    layer: str
    source_code: str
    source_file: str
    source_crs: str
    source_version: str | None
    source_reference: str
    source_retrieved_at: Any
    original_checksum: str | None
    accuracy: float | None
    licence: str
    licence_review_status: str
    commercial_use_allowed: bool
    redistribution_allowed: bool
    share_alike: bool
    permission_reference: str | None
    status: str
    source_features: int
    loaded: int
    rejected: int
    expectations: QaExpectations

    @property
    def label(self) -> str:
        return f"{self.layer} ({self.source_file})"


@dataclass(slots=True)
class QaRunSummary:
    run_id: uuid.UUID
    release_id: uuid.UUID
    release_code: str
    status: QaRunStatus
    check_count: int
    error_count: int
    warning_count: int
    info_count: int
    findings: list[Finding]

    def as_dict(self, *, limit: int = 20) -> dict[str, Any]:
        order = {"error": 0, "warning": 1, "info": 2}
        shown = sorted(self.findings, key=lambda item: order[item.severity])[:limit]
        return {
            "qaRun": str(self.run_id),
            "release": self.release_code,
            "status": self.status,
            "checks": self.check_count,
            "errors": self.error_count,
            "warnings": self.warning_count,
            "infos": self.info_count,
            "findings": [
                {
                    "check": item.check,
                    "severity": item.severity,
                    "layer": item.layer,
                    "sourceFeatureId": item.source_feature_id,
                    "message": item.message,
                }
                for item in shown
            ],
        }


def expectations_for(layer: str, stored: Mapping[str, Any] | None) -> QaExpectations:
    """The dataset's stated expectations, with the layer's defaults for anything it did not state."""
    explicit = QaExpectations.model_validate(stored or {})
    stated = explicit.model_dump(exclude_unset=True)
    return QaExpectations.model_validate({**LAYER_DEFAULTS.get(layer, {}), **stated})


def _status(errors: int, warnings: int) -> QaRunStatus:
    if errors:
        return "failed"
    return "warnings" if warnings else "passed"


def _rows(result: Any) -> Sequence[RowMapping]:
    rows: Sequence[RowMapping] = result.mappings().all()
    return rows


class ReferenceQa:
    """Runs the database checks on a draft release. The caller owns the session and the transaction."""

    def __init__(
        self, session: AsyncSession, *, max_findings_per_check: int = MAX_FINDINGS_PER_CHECK
    ) -> None:
        self._session = session
        self._limit = max_findings_per_check
        self._findings: list[Finding] = []
        self._totals: dict[Severity, int] = {"error": 0, "warning": 0, "info": 0}

    # -- entry point ---------------------------------------------------------------------------------

    async def run(self, release_id: uuid.UUID) -> QaRunSummary:
        release = (
            await self._session.execute(
                text("SELECT id, code, status, purpose FROM meta.ref_data_release WHERE id = :id").bindparams(
                    bindparam("id", type_=UUID)
                ),
                {"id": release_id},
            )
        ).one_or_none()
        if release is None:
            raise ReleaseQaError(f"reference data release {release_id} not found", extensions={})
        if release.status != "draft":
            raise ReleaseQaError(
                f"reference data release {release.code} is {release.status}; only drafts are checked",
                extensions={"refDataRelease": release.code},
            )
        self._findings = []
        self._totals = {"error": 0, "warning": 0, "info": 0}
        production = release.purpose == "production"
        parameters = {
            "purpose": release.purpose,
            "maxFindingsPerCheck": self._limit,
            "checks": [c.code for c in CHECKS],
        }
        run_id = (
            await self._session.execute(
                text(
                    "INSERT INTO meta.qa_run (release_id, stage, tool_version, parameters) "
                    "VALUES (:release_id, 'database', :tool, :parameters) RETURNING id"
                ).bindparams(bindparam("release_id", type_=UUID), bindparam("parameters", type_=JSONB)),
                {
                    "release_id": release_id,
                    "tool": f"gis-core-service {__version__}",
                    "parameters": parameters,
                },
            )
        ).scalar_one()

        loads = await self._loads(release_id)
        await self._release_checks(release_id, loads, production)
        await self._licence_checks(release_id, loads, production)
        await self._crs_checks(release_id, loads)
        await self._geometry_checks(release_id, loads)
        await self._duplicate_checks(release_id, loads)
        await self._identifier_checks(release_id, loads)
        await self._outlier_checks(release_id, loads)
        await self._topology_checks(release_id, loads)
        await self._artifact_checks(release_id)

        await self._store(run_id, release_id)
        status = _status(self._totals["error"], self._totals["warning"])
        await self._session.execute(
            text(
                """
                UPDATE meta.qa_run
                SET status = :status, check_count = :checks, error_count = :errors,
                    warning_count = :warnings, info_count = :infos, finished_at = clock_timestamp(),
                    content_fingerprint = meta.release_fingerprint(release_id)
                WHERE id = :id
                """
            ).bindparams(bindparam("id", type_=UUID)),
            {
                "id": run_id,
                "status": status,
                "checks": len(CHECKS),
                "errors": self._totals["error"],
                "warnings": self._totals["warning"],
                "infos": self._totals["info"],
            },
        )
        summary = QaRunSummary(
            run_id=uuid.UUID(str(run_id)),
            release_id=release_id,
            release_code=release.code,
            status=status,
            check_count=len(CHECKS),
            error_count=self._totals["error"],
            warning_count=self._totals["warning"],
            info_count=self._totals["info"],
            findings=list(self._findings),
        )
        logger.info(
            "reference data QA finished",
            extra={
                "release": release.code,
                "status": status,
                "errors": summary.error_count,
                "warnings": summary.warning_count,
            },
        )
        return summary

    # -- bookkeeping ---------------------------------------------------------------------------------

    def _add(self, finding: Finding, *, total: int = 1) -> None:
        self._findings.append(finding)
        self._totals[finding.severity] += total

    def _add_rows(
        self,
        check: str,
        rows: Sequence[RowMapping],
        make: Any,
        *,
        layer: str | None = None,
        unit: str = "features",
    ) -> None:
        """Add one finding per row (rows carry a window ``total``) and a summary for rows not listed."""
        if not rows:
            return
        total = int(rows[0]["total"])
        worst: Severity = "info"
        for row in rows:
            finding: Finding = make(row)
            self._add(finding)
            if finding.severity == "error" or (finding.severity == "warning" and worst == "info"):
                worst = finding.severity
        remaining = total - len(rows)
        if remaining > 0:
            self._add(
                Finding(
                    check=check,
                    severity=worst,
                    layer=layer,
                    message=f"{remaining} more {unit} with this problem are not listed individually",
                    details={"total": total, "notListed": remaining},
                ),
                total=remaining,
            )

    async def _store(self, run_id: uuid.UUID, release_id: uuid.UUID) -> None:
        if not self._findings:
            return
        statement = text(
            """
            INSERT INTO meta.qa_finding (
                run_id, release_id, check_code, severity, layer_code, load_id, feature_id, source_feature_id,
                message, details, location, waivable)
            VALUES (
                :run_id, :release_id, :check, :severity, :layer, :load_id, :feature_id, :source_feature_id,
                :message, :details, public.ST_GeomFromWKB(:location, 4326), :waivable)
            """
        ).bindparams(
            bindparam("run_id", type_=UUID),
            bindparam("release_id", type_=UUID),
            bindparam("load_id", type_=UUID),
            bindparam("feature_id", type_=UUID),
            bindparam("details", type_=JSONB),
            bindparam("location", type_=BYTEA),
        )
        await self._session.execute(
            statement,
            [
                {
                    "run_id": run_id,
                    "release_id": release_id,
                    "check": item.check,
                    "severity": item.severity,
                    "layer": item.layer,
                    "load_id": item.load_id,
                    "feature_id": item.feature_id,
                    "source_feature_id": item.source_feature_id,
                    "message": item.message,
                    "details": dict(item.details),
                    "location": item.location_wkb,
                    "waivable": WAIVABLE[item.check],
                }
                for item in self._findings
            ],
        )

    async def _fetch(self, sql: str, params: Mapping[str, Any]) -> Sequence[RowMapping]:
        statement = text(sql).bindparams(bindparam("release_id", type_=UUID))
        return _rows(await self._session.execute(statement, {"limit": self._limit, **params}))

    async def _loads(self, release_id: uuid.UUID) -> list[LoadInfo]:
        rows = await self._fetch(
            """
            SELECT l.id, y.code AS layer, s.code AS source_code, l.source_file, l.source_crs,
                   l.source_version, l.source_reference, l.source_retrieved_at, l.original_checksum_sha256,
                   l.geometry_accuracy_m,
                   l.licence, l.licence_review_status, l.commercial_use_allowed, l.redistribution_allowed,
                   l.share_alike, l.permission_reference, l.status, l.source_feature_count, l.loaded_count,
                   l.rejected_count, l.qa_expectations
            FROM meta.dataset_load AS l
            JOIN meta.layer AS y ON y.id = l.layer_id
            JOIN meta.data_source AS s ON s.id = l.source_id
            WHERE l.release_id = :release_id
            ORDER BY y.code, l.started_at, l.id
            """,
            {"release_id": release_id},
        )
        return [
            LoadInfo(
                id=uuid.UUID(str(row["id"])),
                layer=row["layer"],
                source_code=row["source_code"],
                source_file=row["source_file"],
                source_crs=row["source_crs"],
                source_version=row["source_version"],
                source_reference=row["source_reference"],
                source_retrieved_at=row["source_retrieved_at"],
                original_checksum=row["original_checksum_sha256"],
                accuracy=None if row["geometry_accuracy_m"] is None else float(row["geometry_accuracy_m"]),
                licence=row["licence"],
                licence_review_status=row["licence_review_status"],
                commercial_use_allowed=row["commercial_use_allowed"],
                redistribution_allowed=row["redistribution_allowed"],
                share_alike=row["share_alike"],
                permission_reference=row["permission_reference"],
                status=row["status"],
                source_features=row["source_feature_count"],
                loaded=row["loaded_count"],
                rejected=row["rejected_count"],
                expectations=expectations_for(row["layer"], row["qa_expectations"]),
            )
            for row in rows
        ]

    # -- release and lineage -------------------------------------------------------------------------

    async def _release_checks(self, release_id: uuid.UUID, loads: list[LoadInfo], production: bool) -> None:
        if not loads:
            self._add(Finding("release.empty", "warning", "the release has no datasets"))
        for load in loads:
            if load.status != "completed":
                self._add(
                    Finding(
                        "release.load_incomplete",
                        "error",
                        f"{load.label}: load is {load.status}",
                        layer=load.layer,
                        load_id=load.id,
                    )
                )
            if load.accuracy is None:
                self._add(
                    Finding(
                        "metadata.accuracy_missing",
                        "error",
                        f"{load.label}: no nominal accuracy recorded",
                        layer=load.layer,
                        load_id=load.id,
                    )
                )
            if not load.source_version:
                self._add(
                    Finding(
                        "metadata.version_missing",
                        "warning",
                        f"{load.label}: no source version recorded",
                        layer=load.layer,
                        load_id=load.id,
                    )
                )
            if load.source_reference.startswith(NOT_RECORDED_PREFIX):
                self._add(
                    Finding(
                        "metadata.source_not_recorded",
                        "warning",
                        f"{load.label}: the source URL or reference was not recorded",
                        layer=load.layer,
                        load_id=load.id,
                    )
                )
            if load.source_retrieved_at is None or load.original_checksum is None:
                self._add(
                    Finding(
                        "metadata.retrieval_missing",
                        "info",
                        f"{load.label}: retrieval time or checksum of the original file not recorded",
                        layer=load.layer,
                        load_id=load.id,
                    )
                )
        loaded_layers = {load.layer for load in loads if load.loaded > 0}
        for table in TABLES:
            if table.layer not in loaded_layers:
                self._add(
                    Finding(
                        "release.layer_missing",
                        "warning" if production else "info",
                        f"{table.layer} has no data in this release; geo-context reports it as missing",
                        layer=table.layer,
                    )
                )

    # -- licences ------------------------------------------------------------------------------------

    async def _licence_checks(self, release_id: uuid.UUID, loads: list[LoadInfo], production: bool) -> None:
        artifact_sources = await self._fetch(
            """
            SELECT a.name AS artifact, s.code AS source_code, x.licence, x.licence_review_status,
                   x.commercial_use_allowed, x.redistribution_allowed, x.share_alike, x.permission_reference
            FROM meta.release_artifact_source AS x
            JOIN meta.release_artifact AS a ON a.id = x.artifact_id
            JOIN meta.data_source AS s ON s.id = x.source_id
            WHERE x.release_id = :release_id
            ORDER BY a.name, s.code
            """,
            {"release_id": release_id},
        )
        subjects: list[tuple[str, str | None, uuid.UUID | None, Mapping[str, Any]]] = [
            (
                f"{load.label} from {load.source_code}",
                load.layer,
                load.id,
                {
                    "source": load.source_code,
                    "licence": load.licence,
                    "review": load.licence_review_status,
                    "commercial": load.commercial_use_allowed,
                    "redistribution": load.redistribution_allowed,
                    "share_alike": load.share_alike,
                    "permission": load.permission_reference,
                },
            )
            for load in loads
        ] + [
            (
                f"artifact {row['artifact']} from {row['source_code']}",
                None,
                None,
                {
                    "source": row["source_code"],
                    "licence": row["licence"],
                    "review": row["licence_review_status"],
                    "commercial": row["commercial_use_allowed"],
                    "redistribution": row["redistribution_allowed"],
                    "share_alike": row["share_alike"],
                    "permission": row["permission_reference"],
                },
            )
            for row in artifact_sources
        ]
        for label, layer, load_id, licence in subjects:
            details = {"source": licence["source"], "licence": licence["licence"]}
            if licence["review"] == "rejected":
                self._add(
                    Finding(
                        "licence.rejected",
                        "error",
                        f"{label}: the licence review of this source was rejected",
                        layer=layer,
                        load_id=load_id,
                        details=details,
                    )
                )
            elif licence["review"] != "approved":
                self._add(
                    Finding(
                        "licence.unreviewed",
                        "error" if production else "info",
                        f"{label}: licence {licence['licence']} has not been approved for this deployment"
                        + ("" if production else " (acceptable for a non-production release)"),
                        layer=layer,
                        load_id=load_id,
                        details=details,
                    )
                )
            if RESTRICTED_LICENCE.search(licence["licence"]) and not licence["permission"]:
                self._add(
                    Finding(
                        "licence.restricted",
                        "error",
                        f"{label}: licence {licence['licence']} restricts commercial use, redistribution or "
                        "derived data; record the licensor's written permission (permissionReference) or "
                        "remove the source",
                        layer=layer,
                        load_id=load_id,
                        details=details,
                    )
                )
            if production and not (licence["commercial"] or licence["permission"]):
                self._add(
                    Finding(
                        "licence.restricted",
                        "error",
                        f"{label}: the licence does not permit commercial use and no permission is recorded",
                        layer=layer,
                        load_id=load_id,
                        details=details,
                    )
                )
            if licence["share_alike"]:
                self._add(
                    Finding(
                        "licence.share_alike",
                        "info",
                        f"{label}: {licence['licence']} is share-alike; a derived database made available "
                        "outside the platform must be offered under the same licence, with attribution",
                        layer=layer,
                        load_id=load_id,
                        details=details,
                    )
                )
            if not licence["redistribution"]:
                self._add(
                    Finding(
                        "licence.no_redistribution",
                        "info",
                        f"{label}: the data may not leave the platform; exports of this layer are refused",
                        layer=layer,
                        load_id=load_id,
                        details=details,
                    )
                )
        for table in TABLES:
            rows = await self._fetch(
                f"""
                SELECT f.load_id, count(*) AS synthetic, count(*) OVER () AS total
                FROM {table.table} AS f
                WHERE f.release_id = :release_id AND f.geometry_source = 'synthetic'
                GROUP BY f.load_id
                ORDER BY f.load_id
                LIMIT :limit
                """,  # noqa: S608 - table name from TABLES
                {"release_id": release_id},
            )
            self._add_rows(
                "content.synthetic",
                rows,
                lambda row, table=table: Finding(
                    "content.synthetic",
                    "error" if production else "info",
                    f"{table.layer}: {row['synthetic']} synthetic or placeholder features"
                    + (" cannot be published in a production release" if production else ""),
                    layer=table.layer,
                    load_id=uuid.UUID(str(row["load_id"])),
                    details={"features": int(row["synthetic"])},
                ),
                layer=table.layer,
                unit="datasets",
            )

    # -- CRS -----------------------------------------------------------------------------------------

    async def _crs_checks(self, release_id: uuid.UUID, loads: list[LoadInfo]) -> None:
        for table in TABLES:
            row = (
                await self._fetch(
                    f"""
                    SELECT count(*) FILTER (WHERE public.ST_SRID(f.geom) <> 4326) AS wrong_storage,
                           count(*) FILTER (WHERE public.ST_SRID(f.geom_metric) <> 5235) AS wrong_metric
                    FROM {table.table} AS f
                    WHERE f.release_id = :release_id
                    """,  # noqa: S608
                    {"release_id": release_id},
                )
            )[0]
            if row["wrong_storage"]:
                self._add(
                    Finding(
                        "crs.storage_srid",
                        "error",
                        f"{table.layer}: {row['wrong_storage']} geometries are not EPSG:4326",
                        layer=table.layer,
                    ),
                    total=int(row["wrong_storage"]),
                )
            if row["wrong_metric"]:
                self._add(
                    Finding(
                        "crs.metric_srid",
                        "error",
                        f"{table.layer}: {row['wrong_metric']} metric geometries are not EPSG:5235",
                        layer=table.layer,
                    ),
                    total=int(row["wrong_metric"]),
                )
        by_layer: dict[str, set[str]] = {}
        for load in loads:
            normalised = "EPSG:4326" if load.source_crs in WGS84_CRS else load.source_crs
            by_layer.setdefault(load.layer, set()).add(normalised)
        for layer, crs_set in sorted(by_layer.items()):
            if len(crs_set) > 1:
                self._add(
                    Finding(
                        "crs.mixed_sources",
                        "warning",
                        f"{layer} combines sources in {', '.join(sorted(crs_set))}; check that their "
                        "coordinate "
                        "operations agree (datum shifts between Kandawala, SLD99 and WGS 84 reach tens of "
                        "metres to hundreds of metres)",
                        layer=layer,
                        details={"crs": sorted(crs_set)},
                    )
                )

    # -- geometry ------------------------------------------------------------------------------------

    async def _geometry_checks(self, release_id: uuid.UUID, loads: list[LoadInfo]) -> None:
        for table in TABLES:
            rows = await self._fetch(
                f"""
                SELECT f.id, f.load_id, f.source_feature_id, public.ST_IsValidReason(f.geom) AS reason,
                       public.ST_AsBinary(coalesce((public.ST_IsValidDetail(f.geom)).location,
                                                   public.ST_PointOnSurface(f.geom))) AS location,
                       count(*) OVER () AS total
                FROM {table.table} AS f
                WHERE f.release_id = :release_id AND NOT public.ST_IsValid(f.geom, 0)
                ORDER BY f.id
                LIMIT :limit
                """,  # noqa: S608
                {"release_id": release_id},
            )
            self._add_rows(
                "geometry.invalid",
                rows,
                lambda row, table=table: Finding(
                    "geometry.invalid",
                    "error",
                    f"{table.layer} feature {row['source_feature_id']}: invalid geometry ({row['reason']})",
                    layer=table.layer,
                    load_id=uuid.UUID(str(row["load_id"])),
                    feature_id=uuid.UUID(str(row["id"])),
                    source_feature_id=row["source_feature_id"],
                    details={"reason": row["reason"]},
                    location_wkb=bytes(row["location"]),
                ),
                layer=table.layer,
            )

        expectations = {load.id: load.expectations for load in loads}
        repairs = await self._fetch(
            """
            SELECT g.feature_id, g.load_id, g.table_schema || '.' || g.table_name AS layer, g.reason,
                   g.original_area_m2, g.repaired_area_m2,
                   public.ST_HausdorffDistance(
                       public.ST_Boundary(public.ST_Transform(g.original_geom, 5235)),
                       public.ST_Boundary(coalesce(a.geom_metric, p.geom_metric, r.geom_metric,
                                                   w.geom_metric, s.geom_metric))) AS shift_m,
                   public.ST_AsBinary(public.ST_PointOnSurface(public.ST_MakeValid(g.original_geom)))
                       AS location,
                   coalesce(a.source_feature_id, p.source_feature_id, r.source_feature_id,
                            w.source_feature_id,
                            s.source_feature_id) AS source_feature_id,
                   count(*) OVER () AS total
            FROM meta.geometry_repair AS g
            JOIN meta.dataset_load AS l ON l.id = g.load_id
            LEFT JOIN ref.admin_area AS a ON g.table_name = 'admin_area' AND a.id = g.feature_id
            LEFT JOIN ref.protected_area AS p ON g.table_name = 'protected_area' AND p.id = g.feature_id
            LEFT JOIN ref.risk_zone AS r ON g.table_name = 'risk_zone' AND r.id = g.feature_id
            LEFT JOIN ref.water_body AS w ON g.table_name = 'water_body' AND w.id = g.feature_id
            LEFT JOIN ref.settlement AS s ON g.table_name = 'settlement' AND s.id = g.feature_id
            WHERE l.release_id = :release_id
            ORDER BY g.id
            LIMIT :limit
            """,
            {"release_id": release_id},
        )

        def repaired(row: RowMapping) -> Finding:
            expected = expectations.get(uuid.UUID(str(row["load_id"])), QaExpectations())
            original = float(row["original_area_m2"] or 0.0)
            repaired_area = float(row["repaired_area_m2"] or 0.0)
            largest = max(original, repaired_area)
            area_ratio = abs(repaired_area - original) / largest if largest > 0 else 0.0
            shift = float(row["shift_m"]) if row["shift_m"] is not None else math.inf
            severity: Severity = "info"
            if shift > expected.repair_shift_error_m:
                severity = "error"
            elif shift > expected.repair_shift_warn_m or area_ratio > expected.repair_area_warn_ratio:
                severity = "warning"
            return Finding(
                "geometry.repaired",
                severity,
                f"{row['layer']} feature {row['source_feature_id']}: repaired on load ({row['reason']}); "
                f"boundary moved up to {shift:.2f} m, area changed by {area_ratio:.2%}",
                layer=row["layer"],
                load_id=uuid.UUID(str(row["load_id"])),
                feature_id=uuid.UUID(str(row["feature_id"])),
                source_feature_id=row["source_feature_id"],
                details={
                    "reason": row["reason"],
                    "shiftM": None if math.isinf(shift) else round(shift, 3),
                    "originalAreaM2": round(original, 2),
                    "repairedAreaM2": round(repaired_area, 2),
                },
                location_wkb=None if row["location"] is None else bytes(row["location"]),
            )

        self._add_rows("geometry.repaired", repairs, repaired)

        for table in TABLES:
            loads_of = [load for load in loads if load.layer == table.layer]
            for load in loads_of:
                await self._shape_checks(release_id, table, load)

    async def _shape_checks(self, release_id: uuid.UUID, table: ReferenceTable, load: LoadInfo) -> None:
        expected = load.expectations
        params = {"release_id": release_id, "load_id": load.id}
        polygon = "public.GeometryType(f.geom) = 'MULTIPOLYGON'"
        line = "public.GeometryType(f.geom) = 'MULTILINESTRING'"
        base = (
            f"FROM {table.table} AS f WHERE f.release_id = :release_id AND f.load_id = CAST(:load_id AS uuid)"
        )
        feature = (
            "f.id, f.source_feature_id, public.ST_AsBinary(public.ST_PointOnSurface(f.geom)) AS location, "
            "count(*) OVER () AS total"
        )
        if table.kind in ("area", "mixed") and expected.min_area_m2 is not None:
            rows = await self._fetch(
                f"SELECT {feature}, public.ST_Area(f.geom_metric) AS value {base} AND {polygon} "
                "AND public.ST_Area(f.geom_metric) < :minimum ORDER BY f.id LIMIT :limit",
                {**params, "minimum": expected.min_area_m2},
            )
            self._add_rows(
                "geometry.degenerate",
                rows,
                lambda row: self._feature_finding(
                    "geometry.degenerate",
                    "warning",
                    table,
                    load,
                    row,
                    f"area {row['value']:.1f} m² is below {expected.min_area_m2:g} m²",
                    {"areaM2": round(float(row["value"]), 2)},
                ),
                layer=table.layer,
            )
        if table.kind in ("line", "mixed") and expected.min_length_m > 0:
            rows = await self._fetch(
                f"SELECT {feature}, public.ST_Length(f.geom_metric) AS value {base} AND {line} "
                "AND public.ST_Length(f.geom_metric) < :minimum ORDER BY f.id LIMIT :limit",
                {**params, "minimum": expected.min_length_m},
            )
            self._add_rows(
                "geometry.degenerate",
                rows,
                lambda row: self._feature_finding(
                    "geometry.degenerate",
                    "warning",
                    table,
                    load,
                    row,
                    f"length {row['value']:.2f} m is below {expected.min_length_m:g} m",
                    {"lengthM": round(float(row["value"]), 3)},
                ),
                layer=table.layer,
            )
        if table.kind == "area":
            # Isoperimetric quotient 4*pi*A/P^2: 1 for a circle, near 0 for a sliver.
            rows = await self._fetch(
                f"""
                SELECT {feature}, public.ST_Area(f.geom_metric) AS area,
                       4 * pi() * public.ST_Area(f.geom_metric)
                           / nullif(power(public.ST_Perimeter(f.geom_metric), 2), 0) AS value
                {base} AND public.ST_Area(f.geom_metric) < 100000
                  AND 4 * pi() * public.ST_Area(f.geom_metric)
                      / nullif(power(public.ST_Perimeter(f.geom_metric), 2), 0) < 0.01
                ORDER BY f.id LIMIT :limit
                """,
                params,
            )
            self._add_rows(
                "geometry.sliver",
                rows,
                lambda row: self._feature_finding(
                    "geometry.sliver",
                    "warning",
                    table,
                    load,
                    row,
                    f"sliver polygon (compactness {float(row['value']):.4f}, "
                    f"area {float(row['area']):.0f} m²)",
                    {"compactness": round(float(row["value"]), 5), "areaM2": round(float(row["area"]), 1)},
                ),
                layer=table.layer,
            )
        rows = await self._fetch(
            f"SELECT {feature}, public.ST_NPoints(f.geom) AS value {base} "
            "AND public.ST_NPoints(f.geom) > :maximum ORDER BY f.id LIMIT :limit",
            {**params, "maximum": expected.max_vertices},
        )
        self._add_rows(
            "geometry.complexity",
            rows,
            lambda row: self._feature_finding(
                "geometry.complexity",
                "warning",
                table,
                load,
                row,
                f"{row['value']} vertices (more than {expected.max_vertices})",
                {"vertices": int(row["value"])},
            ),
            layer=table.layer,
        )
        if table.kind in ("line", "mixed") and expected.max_segment_m is not None:
            rows = await self._fetch(
                f"""
                SELECT f.id, f.source_feature_id, x.length AS value,
                       public.ST_AsBinary(public.ST_Transform(public.ST_StartPoint(x.segment), 4326))
                           AS location,
                       count(*) OVER () AS total
                FROM {table.table} AS f
                CROSS JOIN LATERAL (
                    SELECT d.geom AS segment, public.ST_Length(d.geom) AS length
                    FROM public.ST_DumpSegments(f.geom_metric) AS d
                    ORDER BY public.ST_Length(d.geom) DESC
                    LIMIT 1
                ) AS x
                WHERE f.release_id = :release_id AND f.load_id = CAST(:load_id AS uuid) AND {line}
                  AND x.length > :maximum
                ORDER BY f.id LIMIT :limit
                """,  # noqa: S608
                {**params, "maximum": expected.max_segment_m},
            )
            self._add_rows(
                "geometry.spike",
                rows,
                lambda row: self._feature_finding(
                    "geometry.spike",
                    "warning",
                    table,
                    load,
                    row,
                    f"a segment is {float(row['value']) / 1000:.1f} km long (more than "
                    f"{expected.max_segment_m / 1000:g} km): a misplaced vertex?",
                    {"segmentM": round(float(row["value"]), 1)},
                ),
                layer=table.layer,
            )

    @staticmethod
    def _feature_finding(
        check: str,
        severity: Severity,
        table: ReferenceTable,
        load: LoadInfo | None,
        row: RowMapping,
        message: str,
        details: Mapping[str, Any],
    ) -> Finding:
        load_id = (
            load.id if load is not None else (uuid.UUID(str(row["load_id"])) if "load_id" in row else None)
        )
        return Finding(
            check,
            severity,
            f"{table.layer} feature {row['source_feature_id']}: {message}",
            layer=table.layer,
            load_id=load_id,
            feature_id=uuid.UUID(str(row["id"])),
            source_feature_id=row["source_feature_id"],
            details=details,
            location_wkb=None if row["location"] is None else bytes(row["location"]),
        )

    # -- duplicates ----------------------------------------------------------------------------------

    async def _duplicate_checks(self, release_id: uuid.UUID, loads: list[LoadInfo]) -> None:
        for table in TABLES:
            rows = await self._fetch(
                f"""
                SELECT (array_agg(f.id ORDER BY f.id))[1] AS id,
                       (array_agg(f.load_id ORDER BY f.id))[1] AS load_id,
                       array_agg(f.source_feature_id ORDER BY f.id) AS source_ids,
                       (array_agg(f.source_feature_id ORDER BY f.id))[1] AS source_feature_id,
                       public.ST_AsBinary(public.ST_PointOnSurface((array_agg(f.geom ORDER BY f.id))[1]))
                           AS location,
                       count(*) AS copies,
                       count(*) OVER () AS total
                FROM {table.table} AS f
                WHERE f.release_id = :release_id
                GROUP BY {"f.level, " if table.layer == "ref.admin_area" else ""}
                         md5(public.ST_AsBinary(public.ST_Normalize(f.geom)))
                HAVING count(*) > 1
                ORDER BY 1
                LIMIT :limit
                """,  # noqa: S608
                {"release_id": release_id},
            )
            severity: Severity = "error" if table.layer == "ref.admin_area" else "warning"
            self._add_rows(
                "duplicate.geometry",
                rows,
                lambda row, table=table, severity=severity: self._feature_finding(
                    "duplicate.geometry",
                    severity,
                    table,
                    None,
                    row,
                    f"{row['copies']} features have exactly the same geometry: "
                    f"{', '.join(map(str, row['source_ids']))}",
                    {"sourceFeatureIds": list(row["source_ids"])},
                ),
                layer=table.layer,
            )

        for layer, type_column in (("ref.settlement", "settlement_type"), ("ref.facility", "facility_type")):
            table = TABLE_BY_LAYER[layer]
            distance = max(
                (load.expectations.duplicate_distance_m or 0.0 for load in loads if load.layer == layer),
                default=0.0,
            )
            if distance <= 0:
                continue
            rows = await self._fetch(
                f"""
                SELECT a.id, a.load_id, a.source_feature_id, b.source_feature_id AS other_id, a.name,
                       public.ST_Distance(a.geom_metric, b.geom_metric) AS distance_m,
                       public.ST_AsBinary(public.ST_PointOnSurface(a.geom)) AS location,
                       count(*) OVER () AS total
                FROM {table.table} AS a
                JOIN {table.table} AS b
                  ON b.release_id = a.release_id AND a.id < b.id
                 AND public.ST_DWithin(a.geom_metric, b.geom_metric, :distance)
                 AND a.{type_column} = b.{type_column}
                 AND lower(btrim(a.name)) = lower(btrim(b.name))
                WHERE a.release_id = :release_id
                ORDER BY a.id, b.id
                LIMIT :limit
                """,  # noqa: S608
                {"release_id": release_id, "distance": distance},
            )
            self._add_rows(
                "duplicate.near",
                rows,
                lambda row, table=table: self._feature_finding(
                    "duplicate.near",
                    "warning",
                    table,
                    None,
                    row,
                    f"'{row['name']}' also appears as {row['other_id']} "
                    f"{float(row['distance_m']):.0f} m away",
                    {
                        "otherSourceFeatureId": row["other_id"],
                        "distanceM": round(float(row["distance_m"]), 1),
                    },
                ),
                layer=layer,
                unit="pairs",
            )

        for layer in ("ref.protected_area", "ref.water_body"):
            table = TABLE_BY_LAYER[layer]
            rows = await self._fetch(
                f"""
                SELECT a.id, a.load_id, a.source_feature_id, b.source_feature_id AS other_id, x.share,
                       public.ST_AsBinary(public.ST_PointOnSurface(a.geom)) AS location,
                       count(*) OVER () AS total
                FROM {table.table} AS a
                JOIN {table.table} AS b
                  ON b.release_id = a.release_id AND a.id < b.id
                 AND a.geom_metric && b.geom_metric
                 AND public.GeometryType(a.geom) = 'MULTIPOLYGON'
                 AND public.GeometryType(b.geom) = 'MULTIPOLYGON'
                 AND public.ST_Intersects(a.geom_metric, b.geom_metric)
                CROSS JOIN LATERAL (
                    SELECT public.ST_Area(public.ST_Intersection(a.geom_metric, b.geom_metric))
                           / nullif(least(public.ST_Area(a.geom_metric), public.ST_Area(b.geom_metric)), 0)
                           AS share
                ) AS x
                WHERE a.release_id = :release_id AND x.share >= 0.9
                ORDER BY a.id, b.id
                LIMIT :limit
                """,  # noqa: S608
                {"release_id": release_id},
            )
            self._add_rows(
                "duplicate.overlap",
                rows,
                lambda row, table=table: self._feature_finding(
                    "duplicate.overlap",
                    "warning",
                    table,
                    None,
                    row,
                    f"{float(row['share']):.0%} of the smaller of it and {row['other_id']} overlap: the same "
                    "feature twice?",
                    {"otherSourceFeatureId": row["other_id"], "share": round(float(row["share"]), 4)},
                ),
                layer=layer,
                unit="pairs",
            )

    # -- identifiers ---------------------------------------------------------------------------------

    async def _identifier_checks(self, release_id: uuid.UUID, loads: list[LoadInfo]) -> None:
        for table in TABLES:
            rows = await self._fetch(
                f"""
                SELECT f.id, f.load_id, f.source_feature_id,
                       public.ST_AsBinary(public.ST_PointOnSurface(f.geom)) AS location,
                       count(*) OVER () AS total
                FROM {table.table} AS f
                WHERE f.release_id = :release_id
                  AND (f.source_feature_id IS NULL OR btrim(f.source_feature_id) = '')
                ORDER BY f.id LIMIT :limit
                """,  # noqa: S608
                {"release_id": release_id},
            )
            self._add_rows(
                "identifier.missing",
                rows,
                lambda row, table=table: self._feature_finding(
                    "identifier.missing", "error", table, None, row, "no source identifier", {}
                ),
                layer=table.layer,
            )
        for table in (TABLE_BY_LAYER["ref.road"], TABLE_BY_LAYER["ref.water_body"]):
            unnamed = (
                await self._fetch(
                    f"SELECT count(*) AS n FROM {table.table} AS f "  # noqa: S608
                    "WHERE f.release_id = :release_id AND f.name IS NULL",
                    {"release_id": release_id},
                )
            )[0]["n"]
            if unnamed:
                self._add(
                    Finding(
                        "identifier.name_missing",
                        "info",
                        f"{table.layer}: {unnamed} features have no name",
                        layer=table.layer,
                        details={"features": int(unnamed)},
                    )
                )
        for load in loads:
            pattern = load.expectations.code_pattern
            if load.layer != "ref.admin_area" or not pattern:
                continue
            rows = await self._fetch(
                """
                SELECT f.id, f.source_feature_id, f.code,
                       public.ST_AsBinary(public.ST_PointOnSurface(f.geom)) AS location,
                       count(*) OVER () AS total
                FROM ref.admin_area AS f
                WHERE f.release_id = :release_id AND f.load_id = CAST(:load_id AS uuid) AND f.code !~ :pattern
                ORDER BY f.id LIMIT :limit
                """,
                {"release_id": release_id, "load_id": load.id, "pattern": pattern},
            )
            table = TABLE_BY_LAYER["ref.admin_area"]
            self._add_rows(
                "identifier.code_format",
                rows,
                lambda row, table=table, load=load, pattern=pattern: self._feature_finding(
                    "identifier.code_format",
                    "warning",
                    table,
                    load,
                    row,
                    f"code {row['code']!r} does not match {pattern}",
                    {"code": row["code"], "pattern": pattern},
                ),
                layer=table.layer,
            )

    # -- outliers ------------------------------------------------------------------------------------

    async def _outlier_checks(self, release_id: uuid.UUID, loads: list[LoadInfo]) -> None:
        await self._outside_country(release_id, loads)
        for load in loads:
            table = TABLE_BY_LAYER[load.layer]
            expected = load.expectations
            params = {"release_id": release_id, "load_id": load.id}
            if expected.expected_bbox is not None:
                pad = expected.extent_tolerance_m * DEGREES_PER_METRE
                min_lon, min_lat, max_lon, max_lat = expected.expected_bbox
                rows = await self._fetch(
                    f"""
                    SELECT f.id, f.source_feature_id,
                           public.ST_AsBinary(public.ST_PointOnSurface(f.geom)) AS location,
                           count(*) OVER () AS total
                    FROM {table.table} AS f
                    WHERE f.release_id = :release_id AND f.load_id = CAST(:load_id AS uuid)
                      AND NOT public.ST_CoveredBy(f.geom, public.ST_MakeEnvelope(:x0, :y0, :x1, :y1, 4326))
                    ORDER BY f.id LIMIT :limit
                    """,  # noqa: S608
                    {
                        **params,
                        "x0": min_lon - pad,
                        "y0": min_lat - pad,
                        "x1": max_lon + pad,
                        "y1": max_lat + pad,
                    },
                )
                self._add_rows(
                    "outlier.extent",
                    rows,
                    lambda row, table=table, load=load: self._feature_finding(
                        "outlier.extent",
                        "error",
                        table,
                        load,
                        row,
                        f"lies outside the expected extent of {load.source_file}",
                        {"expectedBbox": list(load.expectations.expected_bbox or ())},
                    ),
                    layer=table.layer,
                )
                if expected.min_coverage_ratio is not None and load.loaded > 0:
                    extent = (
                        await self._fetch(
                            f"""
                            SELECT public.ST_XMin(b) AS x0, public.ST_YMin(b) AS y0,
                                   public.ST_XMax(b) AS x1, public.ST_YMax(b) AS y1
                            FROM (SELECT public.ST_3DExtent(f.geom) AS b FROM {table.table} AS f
                                  WHERE f.release_id = :release_id
                                    AND f.load_id = CAST(:load_id AS uuid)) AS e
                            """,  # noqa: S608
                            params,
                        )
                    )[0]
                    width = (float(extent["x1"]) - float(extent["x0"])) / (max_lon - min_lon)
                    height = (float(extent["y1"]) - float(extent["y0"])) / (max_lat - min_lat)
                    if min(width, height) < expected.min_coverage_ratio:
                        self._add(
                            Finding(
                                "outlier.coverage",
                                "warning",
                                f"{load.label}: spans {width:.0%} x {height:.0%} of the expected extent "
                                f"(at least {expected.min_coverage_ratio:.0%} expected)",
                                layer=load.layer,
                                load_id=load.id,
                                details={"widthShare": round(width, 3), "heightShare": round(height, 3)},
                            )
                        )
            if expected.min_features is not None and load.loaded < expected.min_features:
                self._add(
                    Finding(
                        "outlier.count",
                        "error",
                        f"{load.label}: {load.loaded} features loaded, "
                        f"at least {expected.min_features} expected",
                        layer=load.layer,
                        load_id=load.id,
                        details={"loaded": load.loaded, "minFeatures": expected.min_features},
                    )
                )
            if expected.max_features is not None and load.loaded > expected.max_features:
                self._add(
                    Finding(
                        "outlier.count",
                        "error",
                        f"{load.label}: {load.loaded} features loaded, "
                        f"at most {expected.max_features} expected",
                        layer=load.layer,
                        load_id=load.id,
                        details={"loaded": load.loaded, "maxFeatures": expected.max_features},
                    )
                )
            if load.rejected:
                share = load.rejected / load.source_features if load.source_features else 1.0
                self._add(
                    Finding(
                        "outlier.rejected",
                        "error" if share > expected.max_rejected_ratio else "info",
                        f"{load.label}: {load.rejected} of {load.source_features} source features were "
                        "rejected "
                        f"({share:.1%}; at most {expected.max_rejected_ratio:.1%} allowed)",
                        layer=load.layer,
                        load_id=load.id,
                        details={"rejected": load.rejected, "sourceFeatures": load.source_features},
                    )
                )
            if table.kind in ("area", "mixed") and expected.max_area_m2 is not None:
                rows = await self._fetch(
                    f"""
                    SELECT f.id, f.source_feature_id, public.ST_Area(f.geom_metric) AS value,
                           public.ST_AsBinary(public.ST_PointOnSurface(f.geom)) AS location,
                           count(*) OVER () AS total
                    FROM {table.table} AS f
                    WHERE f.release_id = :release_id AND f.load_id = CAST(:load_id AS uuid)
                      AND public.GeometryType(f.geom) = 'MULTIPOLYGON'
                      AND public.ST_Area(f.geom_metric) > :maximum
                    ORDER BY f.id LIMIT :limit
                    """,  # noqa: S608
                    {**params, "maximum": expected.max_area_m2},
                )
                self._add_rows(
                    "outlier.area",
                    rows,
                    lambda row, table=table, load=load: self._feature_finding(
                        "outlier.area",
                        "warning",
                        table,
                        load,
                        row,
                        f"area {float(row['value']) / 1e6:.2f} km² is above "
                        f"{(load.expectations.max_area_m2 or 0) / 1e6:g} km²",
                        {"areaM2": round(float(row["value"]), 1)},
                    ),
                    layer=table.layer,
                )
        await self._count_change(release_id, loads)

    async def _outside_country(self, release_id: uuid.UUID, loads: list[LoadInfo]) -> None:
        await self._session.execute(text("DROP TABLE IF EXISTS pg_temp.qa_country"))
        await self._session.execute(
            text(
                """
                CREATE TEMP TABLE qa_country ON COMMIT DROP AS
                WITH outline AS (
                    SELECT public.ST_Union(a.geom_metric) AS geom
                    FROM ref.admin_area AS a
                    WHERE a.release_id = :release_id
                      AND a.level = (SELECT min(b.level) FROM ref.admin_area AS b
                                     WHERE b.release_id = :release_id AND b.level <= 1)
                )
                SELECT public.ST_Subdivide(o.geom, 255) AS geom FROM outline AS o WHERE o.geom IS NOT NULL
                """
            ).bindparams(bindparam("release_id", type_=UUID)),
            {"release_id": release_id},
        )
        await self._session.execute(text("CREATE INDEX ON pg_temp.qa_country USING gist (geom)"))
        await self._session.execute(text("ANALYZE pg_temp.qa_country"))
        has_outline = (
            await self._session.execute(text("SELECT count(*) FROM pg_temp.qa_country"))
        ).scalar_one()
        if not has_outline:
            return
        buffer_by_layer: dict[str, float] = {}
        for load in loads:
            buffer_by_layer[load.layer] = max(
                buffer_by_layer.get(load.layer, 0.0), load.expectations.coast_buffer_m
            )
        for table in TABLES:
            if table.layer == "ref.admin_area" or table.layer not in buffer_by_layer:
                continue
            rows = await self._fetch(
                f"""
                SELECT f.id, f.load_id, f.source_feature_id,
                       public.ST_AsBinary(public.ST_PointOnSurface(f.geom)) AS location,
                       count(*) OVER () AS total
                FROM {table.table} AS f
                WHERE f.release_id = :release_id
                  AND NOT EXISTS (SELECT 1 FROM pg_temp.qa_country AS c
                                  WHERE public.ST_DWithin(f.geom_metric, c.geom, :buffer))
                ORDER BY f.id LIMIT :limit
                """,  # noqa: S608
                {"release_id": release_id, "buffer": buffer_by_layer[table.layer]},
            )
            self._add_rows(
                "outlier.outside_country",
                rows,
                lambda row, table=table: self._feature_finding(
                    "outlier.outside_country",
                    "warning",
                    table,
                    None,
                    row,
                    f"more than {buffer_by_layer[table.layer]:g} m beyond the country outline of this "
                    "release",
                    {"bufferM": buffer_by_layer[table.layer]},
                ),
                layer=table.layer,
            )

    async def _count_change(self, release_id: uuid.UUID, loads: list[LoadInfo]) -> None:
        current = (
            await self._session.execute(
                text("SELECT id, code FROM meta.ref_data_release WHERE is_current AND id <> :id").bindparams(
                    bindparam("id", type_=UUID)
                ),
                {"id": release_id},
            )
        ).one_or_none()
        if current is None:
            return
        counts = await self._fetch(
            """
            SELECT y.code AS layer,
                   coalesce(sum(l.loaded_count) FILTER (WHERE l.release_id = :release_id), 0) AS now,
                   coalesce(sum(l.loaded_count) FILTER (WHERE l.release_id = CAST(:current_id AS uuid)), 0)
                       AS before
            FROM meta.dataset_load AS l
            JOIN meta.layer AS y ON y.id = l.layer_id
            WHERE l.release_id IN (:release_id, CAST(:current_id AS uuid)) AND l.status = 'completed'
            GROUP BY y.code
            ORDER BY y.code
            """,
            {"release_id": release_id, "current_id": current.id},
        )
        ratio_by_layer: dict[str, float] = {}
        for load in loads:
            ratio_by_layer[load.layer] = load.expectations.max_count_change_ratio
        for row in counts:
            before, now = int(row["before"]), int(row["now"])
            if before == 0 or row["layer"] not in ratio_by_layer:
                continue
            change = (now - before) / before
            if abs(change) > ratio_by_layer[row["layer"]]:
                self._add(
                    Finding(
                        "outlier.count_change",
                        "warning",
                        f"{row['layer']}: {now} features against {before} in the current release "
                        f"{current.code} "
                        f"({change:+.0%})",
                        layer=row["layer"],
                        details={"features": now, "currentFeatures": before, "currentRelease": current.code},
                    )
                )

    # -- topology ------------------------------------------------------------------------------------

    async def _topology_checks(self, release_id: uuid.UUID, loads: list[LoadInfo]) -> None:
        admin_loads = [load for load in loads if load.layer == "ref.admin_area"]
        if admin_loads:
            await self._admin_topology(release_id, admin_loads)
        table = TABLE_BY_LAYER["ref.settlement"]
        rows = await self._fetch(
            """
            SELECT f.id, f.load_id, f.source_feature_id,
                   public.ST_AsBinary(f.label_point) AS location, count(*) OVER () AS total
            FROM ref.settlement AS f
            WHERE f.release_id = :release_id AND f.admin_area_id IS NULL
              AND EXISTS (SELECT 1 FROM ref.admin_area AS a WHERE a.release_id = :release_id)
            ORDER BY f.id LIMIT :limit
            """,
            {"release_id": release_id},
        )
        self._add_rows(
            "topology.settlement_unlinked",
            rows,
            lambda row: self._feature_finding(
                "topology.settlement_unlinked",
                "warning",
                table,
                None,
                row,
                "not linked to an administrative area",
                {},
            ),
            layer=table.layer,
        )

    async def _admin_topology(self, release_id: uuid.UUID, admin_loads: list[LoadInfo]) -> None:
        table = TABLE_BY_LAYER["ref.admin_area"]
        expectations = {load.id: load.expectations for load in admin_loads}
        warn_ratio = min(load.expectations.containment_warn_ratio for load in admin_loads)
        rows = await self._fetch(
            """
            SELECT c.id, c.load_id, c.source_feature_id, c.level, p.code AS parent_code, x.share,
                   public.ST_AsBinary(public.ST_PointOnSurface(c.geom)) AS location,
                   count(*) OVER () AS total
            FROM ref.admin_area AS c
            JOIN ref.admin_area AS p ON p.id = c.parent_id AND p.release_id = c.release_id
            CROSS JOIN LATERAL (
                SELECT CASE WHEN public.ST_Covers(p.geom_metric, c.geom_metric) THEN 1.0
                            ELSE public.ST_Area(public.ST_Intersection(c.geom_metric, p.geom_metric))
                                 / nullif(public.ST_Area(c.geom_metric), 0) END AS share
            ) AS x
            WHERE c.release_id = :release_id AND x.share < :warn
            ORDER BY x.share, c.id
            LIMIT :limit
            """,
            {"release_id": release_id, "warn": warn_ratio},
        )

        def parent(row: RowMapping) -> Finding:
            expected = expectations.get(uuid.UUID(str(row["load_id"])), QaExpectations())
            share = float(row["share"] or 0.0)
            if share >= expected.containment_warn_ratio:
                severity: Severity = "info"
            elif share < expected.containment_error_ratio:
                severity = "error"
            else:
                severity = "warning"
            return self._feature_finding(
                "topology.admin_parent",
                severity,
                table,
                None,
                row,
                f"only {share:.1%} of this level {row['level']} area lies inside its parent "
                f"{row['parent_code']}",
                {"share": round(share, 4), "parentCode": row["parent_code"]},
            )

        self._add_rows("topology.admin_parent", rows, parent, layer=table.layer, unit="areas")

        tolerance = min(load.expectations.overlap_tolerance_m2 for load in admin_loads)
        error_ratio = min(load.expectations.overlap_error_ratio for load in admin_loads)
        rows = await self._fetch(
            """
            SELECT a.id, a.load_id, a.source_feature_id, b.source_feature_id AS other_id, a.level, x.area,
                   x.area / nullif(least(public.ST_Area(a.geom_metric), public.ST_Area(b.geom_metric)), 0)
                       AS share,
                   public.ST_AsBinary(public.ST_Transform(public.ST_PointOnSurface(x.overlap), 4326))
                       AS location,
                   count(*) OVER () AS total
            FROM ref.admin_area AS a
            JOIN ref.admin_area AS b
              ON b.release_id = a.release_id AND b.level = a.level AND a.id < b.id
             AND a.geom_metric && b.geom_metric
             AND public.ST_Relate(a.geom_metric, b.geom_metric, '2********')
            CROSS JOIN LATERAL (
                SELECT public.ST_CollectionExtract(
                           public.ST_Intersection(a.geom_metric, b.geom_metric), 3) AS overlap
            ) AS i
            CROSS JOIN LATERAL (SELECT i.overlap, public.ST_Area(i.overlap) AS area) AS x
            WHERE a.release_id = :release_id AND x.area > :tolerance
            ORDER BY x.area DESC, a.id
            LIMIT :limit
            """,
            {"release_id": release_id, "tolerance": tolerance},
        )
        self._add_rows(
            "topology.admin_overlap",
            rows,
            lambda row: self._feature_finding(
                "topology.admin_overlap",
                "error" if float(row["share"] or 0) > error_ratio else "warning",
                table,
                None,
                row,
                f"overlaps level {row['level']} area {row['other_id']} by {float(row['area']) / 1e4:.2f} ha "
                f"({float(row['share'] or 0):.2%} of the smaller)",
                {
                    "otherSourceFeatureId": row["other_id"],
                    "overlapM2": round(float(row["area"]), 1),
                    "share": round(float(row["share"] or 0), 5),
                },
            ),
            layer=table.layer,
            unit="pairs",
        )

        gap_ratio = min(load.expectations.gap_tolerance_ratio for load in admin_loads)
        rows = await self._fetch(
            """
            SELECT p.id, p.load_id, p.source_feature_id, p.level, x.share,
                   public.ST_AsBinary(public.ST_PointOnSurface(p.geom)) AS location,
                   count(*) OVER () AS total
            FROM ref.admin_area AS p
            CROSS JOIN LATERAL (
                SELECT 1 - public.ST_Area(
                               public.ST_Intersection(p.geom_metric, public.ST_Union(c.geom_metric)))
                           / nullif(public.ST_Area(p.geom_metric), 0) AS share
                FROM ref.admin_area AS c
                WHERE c.parent_id = p.id AND c.release_id = p.release_id
                HAVING count(*) > 0
            ) AS x
            WHERE p.release_id = :release_id AND x.share > :ratio
            ORDER BY x.share DESC, p.id
            LIMIT :limit
            """,
            {"release_id": release_id, "ratio": gap_ratio},
        )
        self._add_rows(
            "topology.admin_gap",
            rows,
            lambda row: self._feature_finding(
                "topology.admin_gap",
                "warning",
                table,
                None,
                row,
                f"{float(row['share']):.1%} of this level {row['level']} area is not covered by its children",
                {"uncoveredShare": round(float(row["share"]), 4)},
            ),
            layer=table.layer,
            unit="areas",
        )

    # -- artifacts -----------------------------------------------------------------------------------

    async def _artifact_checks(self, release_id: uuid.UUID) -> None:
        rows = await self._fetch(
            """
            SELECT a.name, count(*) OVER () AS total
            FROM meta.release_artifact AS a
            WHERE a.release_id = :release_id
              AND NOT EXISTS (SELECT 1 FROM meta.release_artifact_source AS s WHERE s.artifact_id = a.id)
            ORDER BY a.name LIMIT :limit
            """,
            {"release_id": release_id},
        )
        self._add_rows(
            "artifact.sources_missing",
            rows,
            lambda row: Finding(
                "artifact.sources_missing",
                "error",
                f"artifact {row['name']} has no recorded sources (licence and attribution unknown)",
                details={"artifact": row["name"]},
            ),
            unit="artifacts",
        )
