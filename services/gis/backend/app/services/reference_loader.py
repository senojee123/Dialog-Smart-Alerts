"""Load reference data (GeoJSON) into a reference data release, with lineage and QA results.

Runs with the migration login (reference tables are read-only for the API login). Input is a manifest
(``manifest.json``, :mod:`app.schemas.reference_data`) listing the release, its data sources with their
licences, and GIS-ready GeoJSON files (``.geojson`` or ``.geojson.gz``):

* each feature has an ``id`` (the source feature id) and properties named after the columns of the
  target table; other properties are kept in ``attributes``
* ``parentBy`` / ``adminAreaBy`` link admin areas to their parent and settlements to the admin area
  they lie in, either by code (``parent_code`` property) or by location (representative
  point, falling back to the nearest area within ``LINK_FALLBACK_M``)

For every file the loader records a ``meta.dataset_load`` row: the source and the exact original file
(reference, version, retrieval time, checksum), the licence as it is at load time, source and storage
CRS and the coordinate operation between them, accuracy, geometry types and extent actually loaded,
counts, the QA expectations, and the pipeline's QA report for the file (a ``meta.qa_run`` of stage
``file``). Coordinates are validated like API input; features outside the service area are counted as
rejected. Invalid polygons are passed to the database, which repairs them and logs the repair
(``meta.geometry_repair``). A file either loads completely or not at all.

Publishing runs the database QA checks first (:mod:`app.services.reference_qa`) and refuses a release
that fails them (:mod:`app.services.reference_releases`).
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Literal

import shapely
from geoalchemy2.shape import from_shape
from pydantic import ValidationError
from shapely.errors import GEOSException
from shapely.geometry import shape as geojson_shape
from sqlalchemy import Date, bindparam, distinct, func, inspect, select, text, update
from sqlalchemy.dialects.postgresql import BYTEA, TSTZRANGE, UUID, Range
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper
from sqlalchemy.types import TypeEngine

from app import __version__
from app.core.config import Environment
from app.core.errors import CoordinateError, GisValidationError, InvalidGeometryError
from app.models.common import GEOMETRY_SOURCES
from app.models.meta import DatasetLoad, DataSource, GeometryRepair, Layer, QaFinding, QaRun, RefDataRelease
from app.models.reference import (
    AdminArea,
    Facility,
    ProtectedArea,
    ReferenceFeature,
    RiskZone,
    Road,
    Settlement,
    WaterBody,
)
from app.schemas.reference_data import (
    FileQaReport,
    FileSpec,
    Manifest,
    ReferenceDataError,
    SourceSpec,
    validation_problems,
)
from app.services.reference_qa import QaRunSummary, ReleaseQaError
from app.services.reference_releases import ReleaseManager
from app.spatial.crs import CANONICAL_SRID
from app.spatial.geometry import LINE_TYPES, POINT_TYPES, POLYGON_TYPES, parse_geojson_geometry
from app.spatial.service_area import ServiceArea

logger = logging.getLogger(__name__)

LINK_FALLBACK_M: Final = 1_000.0
# Columns the loader sets itself; feature properties cannot override them.
MAX_GEOJSON_BYTES: Final = 2 * 1024**3
MAX_FILE_QA_FINDINGS: Final = 1_000
SYSTEM_COLUMNS: Final = frozenset(
    {
        "id",
        "release_id",
        "load_id",
        "source_feature_id",
        "geom",
        "attributes",
        "created_at",
        "updated_at",
        "parent_id",
        "admin_area_id",
    }
)


@dataclass(frozen=True, slots=True)
class LayerSpec:
    model: Callable[..., ReferenceFeature]
    allowed_types: frozenset[str]


LAYERS: Final[Mapping[str, LayerSpec]] = {
    "ref.admin_area": LayerSpec(AdminArea, POLYGON_TYPES),
    "ref.settlement": LayerSpec(Settlement, POINT_TYPES | POLYGON_TYPES),
    "ref.facility": LayerSpec(Facility, POINT_TYPES),
    "ref.road": LayerSpec(Road, LINE_TYPES),
    "ref.water_body": LayerSpec(WaterBody, LINE_TYPES | POLYGON_TYPES),
    "ref.protected_area": LayerSpec(ProtectedArea, POLYGON_TYPES),
    "ref.risk_zone": LayerSpec(RiskZone, POLYGON_TYPES),
}


@dataclass(slots=True)
class FileResult:
    path: str
    layer: str
    load_id: uuid.UUID
    source_features: int = 0
    loaded: int = 0
    repaired: int = 0
    rejected: int = 0
    rejections: list[str] = field(default_factory=list)
    file_qa: str | None = None


@dataclass(slots=True)
class LoadResult:
    release_id: uuid.UUID
    release_code: str
    purpose: str
    files: list[FileResult] = field(default_factory=list)
    published: bool = False
    current: bool = False
    qa: QaRunSummary | None = None


# Kept for callers of the earlier module layout.
ReferenceLoadError = ReferenceDataError


def _as_multi(geometry: shapely.Geometry) -> shapely.Geometry:
    if geometry.geom_type == "Polygon":
        return shapely.MultiPolygon([geometry])
    if geometry.geom_type == "LineString":
        return shapely.MultiLineString([geometry])
    return geometry


def _representative_point(geometry: shapely.Geometry) -> bytes:
    candidate = geometry if shapely.is_valid(geometry) else shapely.make_valid(geometry, method="structure")
    return bytes(shapely.to_wkb(shapely.point_on_surface(candidate), output_dimension=2))


_RANGE = re.compile(r"^([\[(])\s*([^,]*?)\s*,\s*([^\])]*?)\s*([\])])$")


_BOUNDS: Final[dict[str, Literal["()", "[)", "(]", "[]"]]] = {"()": "()", "[)": "[)", "(]": "(]", "[]": "[]"}


def _parse_timestamp(key: str, text_value: str) -> datetime | None:
    if text_value in ("", "infinity", "-infinity"):
        return None
    try:
        value = datetime.fromisoformat(text_value)
    except ValueError as exc:
        raise GisValidationError(f"{key}: {text_value!r} is not an ISO 8601 timestamp") from exc
    if value.tzinfo is None:
        raise GisValidationError(f"{key}: timestamp {text_value!r} needs a UTC offset")
    return value


def _coerce(key: str, column_type: TypeEngine[Any], value: Any) -> Any:
    """Convert JSON property values for the column types JSON cannot express."""
    if value is None or not isinstance(value, str):
        return value
    if isinstance(column_type, TSTZRANGE):
        match = _RANGE.fullmatch(value.strip())
        if match is None:
            raise GisValidationError(f"{key}: {value!r} is not a range like [start,end)")
        lower_bound, lower, upper, upper_bound = match.groups()
        bounds = _BOUNDS[lower_bound + upper_bound]
        return Range(_parse_timestamp(key, lower), _parse_timestamp(key, upper), bounds=bounds)
    if isinstance(column_type, Date):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise GisValidationError(f"{key}: {value!r} is not an ISO 8601 date") from exc
    return value


_ADMIN_BY_LOCATION = text(
    """
    WITH pt AS (
        SELECT public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326) AS geom,
               public.ST_Transform(public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326), 5235) AS geom_metric
    ),
    candidate AS (
        SELECT inside.id, 0 AS rank, 0.0::double precision AS distance
        FROM ref.area_part AS part
        JOIN ref.admin_area AS inside ON inside.id = part.feature_id
        CROSS JOIN pt
        WHERE part.release_id = :release_id AND part.area_kind = 'admin_area'
          AND (CAST(:level AS smallint) IS NULL OR inside.level = CAST(:level AS smallint))
          AND public.ST_Intersects(part.geom, pt.geom)
        UNION ALL
        SELECT near.id, 1, public.ST_Distance(near.geom_metric, pt.geom_metric)
        FROM ref.admin_area AS near CROSS JOIN pt
        WHERE near.release_id = :release_id
          AND (CAST(:level AS smallint) IS NULL OR near.level = CAST(:level AS smallint))
          AND public.ST_DWithin(near.geom_metric, pt.geom_metric, :fallback_m)
    )
    SELECT a.id
    FROM candidate AS c
    JOIN ref.admin_area AS a ON a.id = c.id
    ORDER BY c.rank, a.level DESC, c.distance, a.code
    LIMIT 1
    """
).bindparams(bindparam("release_id", type_=UUID), bindparam("wkb", type_=BYTEA))


class ReferenceDataLoader:
    """Loads a manifest into a draft release. The caller owns the session and the transaction."""

    def __init__(self, session: AsyncSession, service_area: ServiceArea) -> None:
        self._session = session
        self._service_area = service_area

    async def load(
        self,
        manifest_path: Path,
        *,
        release_code: str | None = None,
        publish: bool = False,
        make_current: bool = False,
        environment: Environment | None = None,
    ) -> LoadResult:
        """Load a manifest into its draft release; with ``publish``, run QA and publish if it passes.

        A failing QA run raises :class:`ReleaseQaError` (and the caller's transaction rolls back). Use the
        pipeline CLI to load, check and publish in separate steps and keep the findings.
        """
        manifest = await asyncio.to_thread(Manifest.read, manifest_path)
        base = manifest_path.parent
        await self._upsert_sources(manifest.sources)
        release = await self._draft_release(
            release_code or manifest.release.code, manifest.release.description, manifest.release.purpose
        )
        result = LoadResult(release_id=release.id, release_code=release.code, purpose=release.purpose)
        for spec in manifest.files:
            result.files.append(await self._load_file(release.id, base, spec))
        if publish or make_current:
            manager = ReleaseManager(self._session)
            result.qa = await manager.run_qa(release.code)
            if result.qa.status == "failed":
                raise ReleaseQaError(
                    f"reference data release {release.code} failed QA with {result.qa.error_count} errors",
                    extensions=result.qa.as_dict(),
                )
            await manager.publish(release.code, make_current=make_current, environment=environment)
            result.published = True
            result.current = make_current
        return result

    async def publish(self, release_id: uuid.UUID, *, make_current: bool) -> None:
        """Run QA on a loaded draft and publish it (see :class:`ReleaseManager` for the rules)."""
        code = (
            await self._session.execute(select(RefDataRelease.code).where(RefDataRelease.id == release_id))
        ).scalar_one()
        manager = ReleaseManager(self._session)
        summary = await manager.run_qa(code)
        if summary.status == "failed":
            raise ReleaseQaError(
                f"reference data release {code} failed QA with {summary.error_count} errors",
                extensions=summary.as_dict(),
            )
        await manager.publish(code, make_current=make_current)

    async def _upsert_sources(self, sources: Sequence[SourceSpec]) -> None:
        """Register or update the sources; a licence review stands only while the licence terms do.

        The manifest may record a review decision (approved or rejected, by whom, when, on what basis).
        Without one, an existing decision stands if the terms it was made on did not change; a change of
        licence, commercial use, redistribution, share-alike or permission resets it to ``unreviewed``.
        """
        for source in sources:
            existing = (
                await self._session.execute(select(DataSource).where(DataSource.code == source.code))
            ).scalar_one_or_none()
            review = source.licence_review
            terms = (
                source.licence,
                source.commercial_use_allowed,
                source.redistribution_allowed,
                source.share_alike,
                source.permission_reference,
            )
            values: dict[str, Any] = {
                "name": source.name,
                "publisher": source.publisher,
                "url": source.url,
                "licence": source.licence,
                "licence_url": source.licence_url,
                "attribution": source.attribution,
                "commercial_use_allowed": source.commercial_use_allowed,
                "redistribution_allowed": source.redistribution_allowed,
                "share_alike": source.share_alike,
                "permission_reference": source.permission_reference,
                "notes": source.notes,
            }
            if review.status != "unreviewed":
                values.update(
                    licence_review_status=review.status,
                    licence_reviewed_by=review.reviewed_by,
                    licence_reviewed_on=review.reviewed_on,
                    licence_review_reference=review.reference,
                )
            elif existing is None or terms != (
                existing.licence,
                existing.commercial_use_allowed,
                existing.redistribution_allowed,
                existing.share_alike,
                existing.permission_reference,
            ):
                values.update(
                    licence_review_status="unreviewed",
                    licence_reviewed_by=None,
                    licence_reviewed_on=None,
                    licence_review_reference=None,
                )
            if existing is None:
                self._session.add(DataSource(code=source.code, **values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
        await self._session.flush()

    async def _draft_release(self, code: str, description: str | None, purpose: str) -> RefDataRelease:
        existing = (
            await self._session.execute(select(RefDataRelease).where(RefDataRelease.code == code))
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status != "draft":
                raise ReferenceLoadError(
                    f"release {code} is {existing.status}; load into a new release instead",
                    extensions={"release": code},
                )
            if existing.purpose != purpose:
                raise ReferenceLoadError(
                    f"release {code} is a {existing.purpose} release; this manifest is for {purpose}",
                    extensions={"release": code},
                )
            return existing
        release = RefDataRelease(code=code, description=description, purpose=purpose)
        self._session.add(release)
        await self._session.flush()
        await self._session.refresh(release)
        return release

    async def _load_file(self, release_id: uuid.UUID, base: Path, spec: FileSpec) -> FileResult:
        if spec.geometry_source not in GEOMETRY_SOURCES:
            raise ReferenceLoadError(f"{spec.path}: unknown geometry source {spec.geometry_source!r}")
        path = base / spec.path
        layer_spec = LAYERS[spec.layer]
        layer_id = (
            await self._session.execute(select(Layer.id).where(Layer.code == spec.layer))
        ).scalar_one()
        source = (
            await self._session.execute(select(DataSource).where(DataSource.code == spec.source))
        ).scalar_one_or_none()
        if source is None:
            raise ReferenceLoadError(f"{spec.path}: data source {spec.source!r} is not in the manifest")

        content = await asyncio.to_thread(_read_geojson, path)
        try:
            collection = json.loads(content)
        except ValueError as exc:
            raise ReferenceLoadError(f"{spec.path}: cannot read GeoJSON ({exc})") from exc
        if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
            raise ReferenceLoadError(f"{spec.path}: expected a GeoJSON FeatureCollection")
        features: list[dict[str, Any]] = collection.get("features", [])
        checksum = hashlib.sha256(content).hexdigest()
        report = await asyncio.to_thread(_read_file_qa, base, spec, checksum)
        already_loaded = (
            await self._session.execute(
                select(DatasetLoad.id).where(
                    DatasetLoad.release_id == release_id,
                    DatasetLoad.layer_id == layer_id,
                    DatasetLoad.source_checksum_sha256 == checksum,
                    DatasetLoad.status != "failed",
                )
            )
        ).first()
        if already_loaded is not None:
            raise ReferenceLoadError(
                f"{spec.path} is already loaded into this release; delete that load or use a new release",
                extensions={"loadId": str(already_loaded.id)},
            )

        load = DatasetLoad(
            release_id=release_id,
            layer_id=layer_id,
            source_id=source.id,
            source_version=spec.source_version,
            source_file=path.name,
            source_checksum_sha256=checksum,
            source_crs=spec.source_crs,
            source_feature_count=len(features),
            transformation=spec.transformation,
            loader_version=f"gis-core-service {__version__}",
            source_reference=spec.source_reference,
            source_retrieved_at=spec.source_retrieved_at,
            original_file=spec.original_file,
            original_checksum_sha256=spec.original_checksum_sha256,
            # The licence as it is now: later changes to the source do not rewrite this load's history.
            licence=source.licence,
            licence_url=source.licence_url,
            attribution=source.attribution,
            commercial_use_allowed=source.commercial_use_allowed,
            redistribution_allowed=source.redistribution_allowed,
            share_alike=source.share_alike,
            permission_reference=source.permission_reference,
            licence_review_status=source.licence_review_status,
            coordinate_operation=spec.coordinate_operation,
            geometry_accuracy_m=spec.geometry_accuracy_m,
            qa_expectations=spec.qa.model_dump(mode="json", exclude_unset=True),
            tool_versions=dict(spec.tool_versions),
        )
        self._session.add(load)
        await self._session.flush()
        result = FileResult(path=spec.path, layer=spec.layer, load_id=load.id, source_features=len(features))
        if report is not None:
            await self._record_file_qa(release_id, load.id, report)
            result.file_qa = report.status

        mapper: Mapper[Any] = inspect(layer_spec.model, raiseerr=True)
        settable = {
            attr.key: attr.columns[0].type
            for attr in mapper.column_attrs
            if not attr.columns[0].computed and attr.key not in SYSTEM_COLUMNS
        }
        for index, feature in enumerate(features):
            label = f"{spec.path} feature {feature.get('id', index)!s}"
            try:
                row = await self._build_row(release_id, load.id, spec, layer_spec, settable, feature)
            except (CoordinateError, InvalidGeometryError, GisValidationError) as exc:
                result.rejected += 1
                result.rejections.append(f"{label}: {exc.detail}")
                continue
            self._session.add(row)
            result.loaded += 1
        # Features of later files link to these by location, so they must be in the database now.
        await self._session.flush()

        result.repaired = (
            await self._session.execute(
                select(func.count()).select_from(GeometryRepair).where(GeometryRepair.load_id == load.id)
            )
        ).scalar_one()
        table = layer_spec.model.__table__  # type: ignore[attr-defined]
        geometry_types = sorted(
            (
                await self._session.execute(
                    select(distinct(func.GeometryType(table.c.geom))).where(table.c.load_id == load.id)
                )
            )
            .scalars()
            .all()
        )
        extent = (
            select(func.meta.box_polygon(func.ST_3DExtent(table.c.geom)))
            .where(table.c.load_id == load.id)
            .scalar_subquery()
        )
        await self._session.execute(
            update(DatasetLoad)
            .where(DatasetLoad.id == load.id)
            .values(
                loaded_count=result.loaded,
                repaired_count=result.repaired,
                rejected_count=result.rejected,
                message="; ".join(result.rejections[:20]) or None,
                geometry_types=geometry_types,
                extent=extent,
                status="completed",
                finished_at=func.clock_timestamp(),
            )
        )
        for rejection in result.rejections:
            logger.warning("reference feature rejected", extra={"detail": rejection})
        return result

    async def _record_file_qa(self, release_id: uuid.UUID, load_id: uuid.UUID, report: FileQaReport) -> None:
        counts = {"error": 0, "warning": 0, "info": 0}
        for item in report.findings:
            counts[item.severity] += 1
        run = QaRun(
            release_id=release_id,
            load_id=load_id,
            stage="file",
            status=report.status,
            check_count=len(report.checks),
            error_count=counts["error"],
            warning_count=counts["warning"],
            info_count=counts["info"],
            parameters={
                **report.parameters,
                "checks": report.checks,
                "counts": report.counts,
                "findingCount": report.finding_count,
            },
            tool_version=report.tool_version,
            started_at=report.checked_at,
            finished_at=report.checked_at,
        )
        self._session.add(run)
        await self._session.flush()
        for item in report.findings[:MAX_FILE_QA_FINDINGS]:
            location = None
            if item.location is not None:
                try:
                    location = from_shape(geojson_shape(item.location), srid=CANONICAL_SRID)
                except (ValueError, TypeError, AttributeError, GEOSException):
                    location = None
            self._session.add(
                QaFinding(
                    run_id=run.id,
                    release_id=release_id,
                    check_code=item.check,
                    severity=item.severity,
                    load_id=load_id,
                    source_feature_id=item.source_feature_id,
                    message=item.message,
                    details=item.details,
                    location=location,
                    # File findings describe what the pipeline did (rejections, repairs); publication is
                    # decided by the database checks, so there is nothing to waive here.
                    waivable=True,
                )
            )
        await self._session.flush()

    async def _build_row(
        self,
        release_id: uuid.UUID,
        load_id: uuid.UUID,
        spec: FileSpec,
        layer_spec: LayerSpec,
        settable: Mapping[str, TypeEngine[Any]],
        feature: Mapping[str, Any],
    ) -> ReferenceFeature:
        if feature.get("type") != "Feature" or not isinstance(feature.get("geometry"), dict):
            raise GisValidationError("not a GeoJSON Feature with a geometry")
        source_feature_id = feature.get("id")
        if source_feature_id is None:
            raise GisValidationError("feature has no id")
        validated = parse_geojson_geometry(
            feature["geometry"],
            area=self._service_area,
            allowed_types=layer_spec.allowed_types,
            invalid_polygons="defer",
            max_vertices=250_000,
        )
        properties = {**spec.properties, **(feature.get("properties") or {})}
        values = {
            key: _coerce(key, settable[key], value) for key, value in properties.items() if key in settable
        }
        attributes = {
            key: value
            for key, value in properties.items()
            if key not in settable and key not in {"parent_code"} and value is not None
        }
        values.setdefault("geometry_source", spec.geometry_source)
        if spec.geometry_accuracy_m is not None:
            values.setdefault("geometry_accuracy_m", spec.geometry_accuracy_m)

        model = layer_spec.model
        row = model(
            release_id=release_id,
            load_id=load_id,
            source_feature_id=str(source_feature_id),
            geom=from_shape(_as_multi(validated.geometry), srid=CANONICAL_SRID),
            attributes=attributes,
            **values,
        )
        if isinstance(row, AdminArea):
            level = values.get("level")
            if not isinstance(level, int) or isinstance(level, bool):
                raise GisValidationError("admin areas need an integer 'level' property")
            if spec.parent_by is not None and level >= 2:
                row.parent_id = await self._parent_of(release_id, spec, properties, validated.geometry)
        if isinstance(row, Settlement) and spec.admin_area_by == "location":
            row.admin_area_id = await self._admin_area_at(
                release_id, _representative_point(validated.geometry), None
            )
        return row

    async def _parent_of(
        self,
        release_id: uuid.UUID,
        spec: FileSpec,
        properties: Mapping[str, Any],
        geometry: shapely.Geometry,
    ) -> uuid.UUID:
        level = int(properties["level"]) - 1
        if spec.parent_by == "code":
            parent_code = properties.get("parent_code")
            parent = (
                await self._session.execute(
                    select(AdminArea.id).where(
                        AdminArea.release_id == release_id,
                        AdminArea.level == level,
                        AdminArea.code == str(parent_code),
                    )
                )
            ).scalar_one_or_none()
        else:
            parent = await self._admin_area_at(release_id, _representative_point(geometry), level)
        if parent is None:
            raise GisValidationError(f"no level {level} parent found ({spec.parent_by})")
        return parent

    async def _admin_area_at(
        self, release_id: uuid.UUID, point_wkb: bytes, level: int | None
    ) -> uuid.UUID | None:
        value = (
            await self._session.execute(
                _ADMIN_BY_LOCATION,
                {"release_id": release_id, "wkb": point_wkb, "level": level, "fallback_m": LINK_FALLBACK_M},
            )
        ).scalar_one_or_none()
        return None if value is None else uuid.UUID(str(value))


def _read_geojson(path: Path) -> bytes:
    """The GeoJSON content of ``path`` (decompressed for ``.gz``), refusing implausibly large files."""
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as stream:
                content = stream.read(MAX_GEOJSON_BYTES + 1)
        else:
            content = path.read_bytes()
    except (OSError, EOFError) as exc:
        raise ReferenceLoadError(f"{path.name}: cannot read GeoJSON ({exc})") from exc
    if len(content) > MAX_GEOJSON_BYTES:
        raise ReferenceLoadError(f"{path.name}: more than {MAX_GEOJSON_BYTES} bytes of GeoJSON")
    return content


def _read_file_qa(base: Path, spec: FileSpec, checksum: str) -> FileQaReport | None:
    if spec.qa_report is None:
        return None
    path = base / spec.qa_report
    try:
        report = FileQaReport.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReferenceLoadError(
            f"{spec.path}: cannot read QA report {spec.qa_report} ({exc.strerror})"
        ) from exc
    except ValidationError as exc:
        raise ReferenceLoadError(
            f"{spec.path}: invalid QA report {spec.qa_report}",
            extensions={"errors": validation_problems(exc)},
        ) from exc
    if report.sha256 != checksum:
        raise ReferenceLoadError(
            f"{spec.path}: the QA report {spec.qa_report} was made for different content "
            f"(sha256 {report.sha256}, file {checksum}); rebuild the file",
            extensions={"reportSha256": report.sha256, "fileSha256": checksum},
        )
    if report.status == "failed":
        raise ReferenceLoadError(
            f"{spec.path}: the pipeline's QA checks failed for this file; see {spec.qa_report}",
            extensions={"qaReport": spec.qa_report},
        )
    return report
