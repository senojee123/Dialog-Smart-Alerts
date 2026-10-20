"""Reference data release management: QA, publication, the current release, retirement, waivers, reports.

A release moves ``draft -> published -> retired`` (ADR-0013). This service is how operators (through the
pipeline CLI) and the loader move it, with the rules the database enforces made readable:

* **QA first.** :meth:`ReleaseManager.run_qa` runs the database checks (:mod:`app.services.reference_qa`).
  :meth:`publish` refuses a release whose latest QA run failed, is stale, or is missing - and the database
  refuses it too (``meta.guard_release_transition``), so the rule holds for any login.
* **Waivers are explicit.** An error can be accepted with a reason (:meth:`waive`); the database records
  who and when, audits it, and refuses waivers of checks that cannot be waived.
* **Production runs production data.** In a production environment only a *production* release can be
  made current; development and test releases (open data, placeholders) cannot reach it by accident.
* **One current release.** Making a release current unsets the previous one in the same transaction.

Reports (:meth:`report`, :meth:`diff`) describe a release from its lineage: datasets, sources and
licences as imported, QA results and artifacts.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment
from app.core.errors import GisError, NotFoundError
from app.repositories.pg_errors import server_message, sqlstate
from app.schemas.reference_data import merge_attribution
from app.services.reference_qa import QaRunSummary, ReferenceQa, ReleaseQaError

OBJECT_NOT_IN_PREREQUISITE_STATE: Final = "55000"
CHECK_VIOLATION: Final = "23514"


class ReleaseNotFoundError(NotFoundError):
    code = "release_not_found"
    title = "Reference data release not found"


class ReleaseStateError(GisError):
    status_code = 409
    code = "release_state_conflict"
    title = "Reference data release cannot make this transition"


@dataclass(frozen=True, slots=True)
class ReleaseRecord:
    id: uuid.UUID
    code: str
    status: str
    purpose: str
    is_current: bool
    description: str | None
    published_at: datetime | None
    retired_at: datetime | None


@dataclass(frozen=True, slots=True)
class ArtifactSourceSpec:
    source_code: str
    role: str
    source_reference: str
    source_version: str | None = None
    source_checksum_sha256: str | None = None
    source_retrieved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    kind: str
    name: str
    uri: str
    media_type: str
    sha256: str
    size_bytes: int
    crs: str
    transformation: str
    sources: Sequence[ArtifactSourceSpec]
    min_zoom: int | None = None
    max_zoom: int | None = None
    bounds: tuple[float, float, float, float] | None = None
    geometry_types: Sequence[str] = ()
    geometry_accuracy_m: float | None = None
    metadata: Mapping[str, Any] | None = None
    tool_versions: Mapping[str, str] | None = None


def _database_refusal(error: DBAPIError, fallback: type[GisError], **extensions: Any) -> GisError:
    """A trigger's refusal (SQLSTATE 55000 / 23514) as a readable error; anything else is re-raised."""
    if sqlstate(error) in (OBJECT_NOT_IN_PREREQUISITE_STATE, CHECK_VIOLATION):
        return fallback(server_message(error), extensions=extensions)
    raise error


class ReleaseManager:
    """Release lifecycle operations. The caller owns the session and the transaction (migration login)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def release(self, code: str) -> ReleaseRecord:
        row = (
            await self._session.execute(
                text(
                    "SELECT id, code, status, purpose, is_current, description, published_at, retired_at "
                    "FROM meta.ref_data_release WHERE code = :code"
                ),
                {"code": code},
            )
        ).one_or_none()
        if row is None:
            raise ReleaseNotFoundError(
                f"reference data release {code} not found", extensions={"refDataRelease": code}
            )
        return ReleaseRecord(
            id=uuid.UUID(str(row.id)),
            code=row.code,
            status=row.status,
            purpose=row.purpose,
            is_current=row.is_current,
            description=row.description,
            published_at=row.published_at,
            retired_at=row.retired_at,
        )

    async def releases(self) -> list[ReleaseRecord]:
        rows = (
            await self._session.execute(
                text(
                    "SELECT id, code, status, purpose, is_current, description, published_at, retired_at "
                    "FROM meta.ref_data_release ORDER BY created_at DESC, code"
                )
            )
        ).all()
        return [
            ReleaseRecord(
                uuid.UUID(str(row.id)),
                row.code,
                row.status,
                row.purpose,
                row.is_current,
                row.description,
                row.published_at,
                row.retired_at,
            )
            for row in rows
        ]

    # -- QA and publication --------------------------------------------------------------------------

    async def run_qa(self, code: str) -> QaRunSummary:
        release = await self.release(code)
        return await ReferenceQa(self._session).run(release.id)

    async def publish(
        self, code: str, *, make_current: bool = False, environment: Environment | None = None
    ) -> ReleaseRecord:
        release = await self.release(code)
        if release.status != "draft":
            raise ReleaseStateError(
                f"reference data release {code} is {release.status}; only a draft can be published",
                extensions={"refDataRelease": code, "releaseStatus": release.status},
            )
        if make_current:
            self._check_environment(release, environment)
        latest = await self.latest_qa(release.id)
        if latest is None:
            raise ReleaseQaError(
                f"reference data release {code} has not been checked; run the QA checks first",
                extensions={"refDataRelease": code},
            )
        if not latest["fresh"]:
            raise ReleaseQaError(
                f"reference data release {code} changed after its last QA run {latest['id']}; run the QA "
                "checks again",
                extensions={"refDataRelease": code, "qaRun": str(latest["id"])},
            )
        if latest["status"] == "failed" and latest["open_errors"]:
            raise ReleaseQaError(
                f"reference data release {code} has {latest['open_errors']} unresolved QA errors "
                f"(QA run {latest['id']}); fix the data or waive them with a reason",
                extensions={
                    "refDataRelease": code,
                    "qaRun": str(latest["id"]),
                    "errors": latest["open_errors"],
                },
            )
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    text("UPDATE meta.ref_data_release SET status = 'published' WHERE id = :id").bindparams(
                        bindparam("id", type_=UUID)
                    ),
                    {"id": release.id},
                )
        except DBAPIError as error:
            raise _database_refusal(error, ReleaseQaError, refDataRelease=code) from error
        if make_current:
            await self._set_current(release.id)
        return await self.release(code)

    async def make_current(self, code: str, *, environment: Environment | None = None) -> ReleaseRecord:
        release = await self.release(code)
        if release.status != "published":
            raise ReleaseStateError(
                f"reference data release {code} is {release.status}; only a published release can be current",
                extensions={"refDataRelease": code, "releaseStatus": release.status},
            )
        self._check_environment(release, environment)
        await self._set_current(release.id)
        return await self.release(code)

    async def retire(self, code: str) -> ReleaseRecord:
        release = await self.release(code)
        if release.status != "published":
            raise ReleaseStateError(
                f"reference data release {code} is {release.status}; only a published release can be retired",
                extensions={"refDataRelease": code, "releaseStatus": release.status},
            )
        if release.is_current:
            raise ReleaseStateError(
                f"reference data release {code} is current; make another release current first",
                extensions={"refDataRelease": code},
            )
        await self._session.execute(
            text("UPDATE meta.ref_data_release SET status = 'retired' WHERE id = :id").bindparams(
                bindparam("id", type_=UUID)
            ),
            {"id": release.id},
        )
        return await self.release(code)

    async def waive(self, code: str, finding_id: int, reason: str) -> None:
        release = await self.release(code)
        try:
            async with self._session.begin_nested():
                updated = (
                    await self._session.execute(
                        text(
                            "UPDATE meta.qa_finding SET waiver_reason = :reason "
                            "WHERE id = :finding AND release_id = :release_id RETURNING id"
                        ).bindparams(bindparam("release_id", type_=UUID)),
                        {"reason": reason, "finding": finding_id, "release_id": release.id},
                    )
                ).scalar_one_or_none()
        except DBAPIError as error:
            raise _database_refusal(
                error, ReleaseStateError, refDataRelease=code, finding=finding_id
            ) from error
        if updated is None:
            raise NotFoundError(
                f"QA finding {finding_id} does not belong to release {code}",
                extensions={"refDataRelease": code, "finding": finding_id},
            )

    async def latest_qa(self, release_id: uuid.UUID) -> dict[str, Any] | None:
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT q.id, q.status, q.started_at, q.finished_at, q.error_count, q.warning_count,
                               q.info_count, q.check_count,
                               q.content_fingerprint IS NOT DISTINCT FROM
                                   meta.release_fingerprint(q.release_id)
                                   AS fresh,
                               (SELECT count(*) FROM meta.qa_finding AS f
                                WHERE f.run_id = q.id AND f.severity = 'error' AND f.waived_at IS NULL)
                                   AS open_errors
                        FROM meta.qa_run AS q
                        WHERE q.release_id = :release_id AND q.stage = 'database' AND q.status <> 'running'
                        ORDER BY q.started_at DESC, q.id DESC
                        LIMIT 1
                        """
                    ).bindparams(bindparam("release_id", type_=UUID)),
                    {"release_id": release_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else dict(row)

    @staticmethod
    def _check_environment(release: ReleaseRecord, environment: Environment | None) -> None:
        if environment is Environment.PRODUCTION and release.purpose != "production":
            raise ReleaseStateError(
                f"reference data release {release.code} is a {release.purpose} release; a production "
                "environment only serves production releases",
                extensions={"refDataRelease": release.code, "purpose": release.purpose},
            )

    async def _set_current(self, release_id: uuid.UUID) -> None:
        await self._session.execute(
            text(
                "UPDATE meta.ref_data_release SET is_current = false WHERE is_current AND id <> :id"
            ).bindparams(bindparam("id", type_=UUID)),
            {"id": release_id},
        )
        await self._session.execute(
            text("UPDATE meta.ref_data_release SET is_current = true WHERE id = :id").bindparams(
                bindparam("id", type_=UUID)
            ),
            {"id": release_id},
        )

    # -- artifacts -----------------------------------------------------------------------------------

    async def register_artifact(self, code: str, artifact: ArtifactSpec) -> uuid.UUID:
        """Record a file built for a draft release (the basemap), with its sources' licences as of now."""
        release = await self.release(code)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    text(
                        "DELETE FROM meta.release_artifact WHERE release_id = :release_id AND name = :name"
                    ).bindparams(bindparam("release_id", type_=UUID)),
                    {"release_id": release.id, "name": artifact.name},
                )
                bounds = artifact.bounds
                artifact_id = (
                    await self._session.execute(
                        text(
                            """
                            INSERT INTO meta.release_artifact (
                                release_id, kind, name, uri, media_type, sha256, size_bytes, crs, min_zoom,
                                max_zoom, bounds, geometry_types, geometry_accuracy_m, transformation,
                                    metadata,
                                tool_versions)
                            VALUES (
                                :release_id, :kind, :name, :uri, :media_type, :sha256, :size_bytes, :crs,
                                :min_zoom, :max_zoom,
                                CASE WHEN CAST(:x0 AS double precision) IS NULL THEN NULL
                                     ELSE public.ST_MakeEnvelope(:x0, :y0, :x1, :y1, 4326) END,
                                CAST(:geometry_types AS text[]), :accuracy, :transformation, :metadata,
                                :tool_versions)
                            RETURNING id
                            """
                        ).bindparams(
                            bindparam("release_id", type_=UUID),
                            bindparam("metadata", type_=JSONB),
                            bindparam("tool_versions", type_=JSONB),
                        ),
                        {
                            "release_id": release.id,
                            "kind": artifact.kind,
                            "name": artifact.name,
                            "uri": artifact.uri,
                            "media_type": artifact.media_type,
                            "sha256": artifact.sha256,
                            "size_bytes": artifact.size_bytes,
                            "crs": artifact.crs,
                            "min_zoom": artifact.min_zoom,
                            "max_zoom": artifact.max_zoom,
                            "x0": None if bounds is None else bounds[0],
                            "y0": None if bounds is None else bounds[1],
                            "x1": None if bounds is None else bounds[2],
                            "y1": None if bounds is None else bounds[3],
                            "geometry_types": list(artifact.geometry_types),
                            "accuracy": artifact.geometry_accuracy_m,
                            "transformation": artifact.transformation,
                            "metadata": dict(artifact.metadata or {}),
                            "tool_versions": dict(artifact.tool_versions or {}),
                        },
                    )
                ).scalar_one()
                for source in artifact.sources:
                    inserted = (
                        await self._session.execute(
                            text(
                                """
                                INSERT INTO meta.release_artifact_source (
                                    artifact_id, release_id, source_id, role, source_version,
                                        source_reference,
                                    source_checksum_sha256, source_retrieved_at, licence, licence_url,
                                    attribution, commercial_use_allowed, redistribution_allowed, share_alike,
                                    permission_reference, licence_review_status)
                                SELECT :artifact_id, :release_id, s.id, :role, :version, :reference,
                                       :checksum,
                                       :retrieved_at, s.licence, s.licence_url, s.attribution,
                                       s.commercial_use_allowed, s.redistribution_allowed, s.share_alike,
                                       s.permission_reference, s.licence_review_status
                                FROM meta.data_source AS s
                                WHERE s.code = :source_code
                                RETURNING source_id
                                """
                            ).bindparams(
                                bindparam("artifact_id", type_=UUID), bindparam("release_id", type_=UUID)
                            ),
                            {
                                "artifact_id": artifact_id,
                                "release_id": release.id,
                                "role": source.role,
                                "version": source.source_version,
                                "reference": source.source_reference,
                                "checksum": source.source_checksum_sha256,
                                "retrieved_at": source.source_retrieved_at,
                                "source_code": source.source_code,
                            },
                        )
                    ).scalar_one_or_none()
                    if inserted is None:
                        raise ReleaseStateError(
                            f"artifact {artifact.name}: data source {source.source_code} is not registered",
                            extensions={"refDataRelease": code, "source": source.source_code},
                        )
        except DBAPIError as error:
            raise _database_refusal(error, ReleaseStateError, refDataRelease=code) from error
        return uuid.UUID(str(artifact_id))

    # -- reports -------------------------------------------------------------------------------------

    async def report(self, code: str, *, findings_limit: int = 200) -> dict[str, Any]:
        """Everything recorded about a release: datasets with lineage and licences, QA, artifacts."""
        release = await self.release(code)
        datasets = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT layer_code, source_code, source_name, publisher, licence, licence_url,
                               attribution,
                               commercial_use_allowed, redistribution_allowed, share_alike,
                                   licence_review_status,
                               source_reference, source_version, source_file, source_checksum_sha256,
                               source_retrieved_at, original_file, original_checksum_sha256, source_crs,
                               storage_crs, coordinate_operation, transformation, geometry_types,
                               geometry_accuracy_m, public.ST_AsText(extent) AS extent, source_feature_count,
                               loaded_count, repaired_count, rejected_count, load_status, imported_at,
                                   finished_at,
                               loaded_by, loader_version, tool_versions
                        FROM meta.dataset_lineage
                        WHERE release_id = :release_id
                        ORDER BY layer_code, imported_at
                        """
                    ).bindparams(bindparam("release_id", type_=UUID)),
                    {"release_id": release.id},
                )
            )
            .mappings()
            .all()
        )
        artifacts = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT a.kind, a.name, a.uri, a.media_type, a.sha256, a.size_bytes, a.crs, a.min_zoom,
                               a.max_zoom, public.ST_AsText(a.bounds) AS bounds, a.geometry_types,
                               a.transformation, a.created_at,
                               coalesce((SELECT jsonb_agg(jsonb_build_object(
                                            'source', s.code, 'role', x.role, 'licence', x.licence,
                                            'attribution', x.attribution, 'version', x.source_version,
                                            'reference', x.source_reference) ORDER BY s.code)
                                         FROM meta.release_artifact_source AS x
                                         JOIN meta.data_source AS s ON s.id = x.source_id
                                         WHERE x.artifact_id = a.id), '[]'::jsonb) AS sources
                        FROM meta.release_artifact AS a
                        WHERE a.release_id = :release_id
                        ORDER BY a.name
                        """
                    ).bindparams(bindparam("release_id", type_=UUID)),
                    {"release_id": release.id},
                )
            )
            .mappings()
            .all()
        )
        qa_runs = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT q.id, q.stage, q.status, l.source_file, q.error_count, q.warning_count,
                               q.info_count, q.started_at, q.finished_at, q.run_by
                        FROM meta.qa_run AS q
                        LEFT JOIN meta.dataset_load AS l ON l.id = q.load_id
                        WHERE q.release_id = :release_id
                        ORDER BY q.started_at, q.id
                        """
                    ).bindparams(bindparam("release_id", type_=UUID)),
                    {"release_id": release.id},
                )
            )
            .mappings()
            .all()
        )
        latest = await self.latest_qa(release.id)
        findings: Sequence[Any] = ()
        if latest is not None:
            findings = (
                (
                    await self._session.execute(
                        text(
                            """
                            SELECT f.id, f.check_code, f.severity, f.layer_code, f.source_feature_id,
                                   f.message,
                                   f.details, public.ST_AsText(f.location) AS location, f.waivable,
                                       f.waived_at,
                                   f.waived_by, f.waiver_reason
                            FROM meta.qa_finding AS f
                            WHERE f.run_id = :run_id
                            ORDER BY CASE f.severity WHEN 'error' THEN 0 WHEN 'warning' THEN 1 ELSE 2
                                   END, f.id
                            LIMIT :limit
                            """
                        ).bindparams(bindparam("run_id", type_=UUID)),
                        {"run_id": latest["id"], "limit": findings_limit},
                    )
                )
                .mappings()
                .all()
            )
        attributions = merge_attribution(
            sorted(
                {row["attribution"] for row in datasets}
                | {s["attribution"] for a in artifacts for s in a["sources"]}
            )
        )
        return {
            "release": {
                "code": release.code,
                "status": release.status,
                "purpose": release.purpose,
                "isCurrent": release.is_current,
                "description": release.description,
                "publishedAt": release.published_at,
                "retiredAt": release.retired_at,
            },
            "attributions": attributions,
            "datasets": [dict(row) for row in datasets],
            "artifacts": [dict(row) for row in artifacts],
            "qa": {
                "latest": latest,
                "runs": [dict(row) for row in qa_runs],
                "findings": [dict(row) for row in findings],
            },
        }

    async def diff(self, code: str, against: str | None = None) -> dict[str, Any]:
        """Per layer: feature counts, and source ids added and removed, against another release."""
        release = await self.release(code)
        if against is None:
            current = (
                await self._session.execute(
                    text("SELECT code FROM meta.ref_data_release WHERE is_current AND code <> :code"),
                    {"code": code},
                )
            ).scalar_one_or_none()
            if current is None:
                return {"release": code, "against": None, "layers": []}
            against = current
        other = await self.release(against)
        layers: list[dict[str, Any]] = []
        for table in (
            "admin_area",
            "settlement",
            "facility",
            "road",
            "water_body",
            "protected_area",
            "risk_zone",
        ):
            row = (
                await self._session.execute(
                    text(
                        f"""
                        SELECT count(*) FILTER (WHERE n.release_id = :new) AS now,
                               count(*) FILTER (WHERE n.release_id = :old) AS before,
                               (SELECT count(*) FROM ref.{table} AS a
                                WHERE a.release_id = :new AND NOT EXISTS (
                                    SELECT 1 FROM ref.{table} AS b
                                    WHERE b.release_id = :old AND b.source_feature_id = a.source_feature_id))
                                   AS added,
                               (SELECT count(*) FROM ref.{table} AS b
                                WHERE b.release_id = :old AND NOT EXISTS (
                                    SELECT 1 FROM ref.{table} AS a
                                    WHERE a.release_id = :new AND a.source_feature_id = b.source_feature_id))
                                   AS removed
                        FROM ref.{table} AS n
                        WHERE n.release_id IN (:new, :old)
                        """  # noqa: S608 - table names are the constants above
                    ).bindparams(bindparam("new", type_=UUID), bindparam("old", type_=UUID)),
                    {"new": release.id, "old": other.id},
                )
            ).one()
            layers.append(
                {
                    "layer": f"ref.{table}",
                    "features": int(row.now),
                    "featuresBefore": int(row.before),
                    "added": int(row.added),
                    "removed": int(row.removed),
                }
            )
        return {"release": code, "against": against, "layers": layers}
