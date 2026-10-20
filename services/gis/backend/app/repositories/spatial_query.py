"""SQL for the spatial query API: layer features, proximity, containment, events, reverse geocoding.

How a statement is built (ARCHITECTURE.md, "SQL and query safety"):

* every table, column and expression comes from :mod:`app.spatial.layers`; the service has already
  translated the request's layer and filter *names* into those constants
* every value - geometries as WKB, distances, instants, filter values, cursor keys, limits - is a bound
  parameter, cast explicitly so NULL keeps its type
* which conditions a statement has depends only on which filters were given, never on their values, so
  each combination is one plan the database can reuse

Spatial conventions are those of the rest of the service: containment in EPSG:4326, boundary inclusive;
distances and radii in EPSG:5235, inclusive; tenant tables state the bounding-box test (``&&``)
explicitly so row-level security cannot hide the index (ADR-0014).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from app.repositories.spatial_lookup import (
    AdminAreaRow,
    ReleaseRow,
    RoadRow,
    SettlementRow,
    admin_row,
    as_uuid,
    missing_layer,
    road_row,
    settlement_row,
)
from app.schemas.geo_context import ReferenceLayerName
from app.spatial.layers import EVENTS, Property, SpatialLayer

# About 1 cm; the same precision the rest of the API emits.
GEOJSON_DECIMALS: Final = 7
METRIC_SRID: Final = 5235
# Segments per quarter circle when a corridor's half-width is drawn for a covering test. A buffer polygon
# lies inside the true shape by radius * (1 - cos(pi / (4 * quad_segs))): under a centimetre at 5 km, the
# largest half-width the data model allows.
COVERS_QUAD_SEGS: Final = 512


class UnsupportedFilterError(ValueError):
    """A filter that the layer does not have reached the repository (the service rejects these first)."""


@dataclass(frozen=True, slots=True)
class LayerRow:
    """A row of the layer registry ``meta.layer``."""

    code: str
    name: str
    description: str
    layer_group: str
    geometry_types: tuple[str, ...]
    srid: int
    metric_srid: int
    tenant_scoped: bool
    default_sharing_policy: str | None
    update_frequency: str
    nominal_accuracy_m: float | None


@dataclass(frozen=True, slots=True)
class FeatureRow:
    id: uuid.UUID
    geometry: dict[str, Any] | None
    properties: dict[str, Any]
    distance_m: float | None = None
    relation: str | None = None


@dataclass(frozen=True, slots=True)
class EventRow:
    event_id: str
    observed_at: datetime
    geometry: dict[str, Any] | None
    properties: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReverseRow:
    admin_areas: tuple[AdminAreaRow, ...]
    settlement: SettlementRow | None
    road: RoadRow | None
    missing_layers: tuple[ReferenceLayerName, ...]


Bbox = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class FeatureQuery:
    """Features of one layer, ordered by id (the keyset paging order)."""

    layer: SpatialLayer
    limit: int
    release_id: uuid.UUID | None = None
    bbox: Bbox | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)
    name_contains: str | None = None
    at: datetime | None = None
    include_geometry: bool = True
    after_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class DistanceQuery:
    """Features within ``distance_m`` of a geometry, nearest first."""

    layer: SpatialLayer
    limit: int
    geometry_wkb: bytes
    distance_m: float
    release_id: uuid.UUID | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)
    name_contains: str | None = None
    at: datetime | None = None
    include_geometry: bool = True
    after_distance_m: float | None = None
    after_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ContainmentQuery:
    """Areas that cover (or intersect) a geometry, ordered by id."""

    layer: SpatialLayer
    limit: int
    geometry_wkb: bytes
    covers: bool = True
    release_id: uuid.UUID | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)
    name_contains: str | None = None
    at: datetime | None = None
    include_geometry: bool = True
    after_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class EventQuery:
    """Event locations of the transaction's tenant in a bounded time window, newest first."""

    time_from: datetime
    time_to: datetime
    limit: int
    bbox: Bbox | None = None
    filters: Mapping[str, Any] = field(default_factory=dict)
    geofence_id: uuid.UUID | None = None
    admin_area_id: uuid.UUID | None = None
    admin_area_code: str | None = None
    include_geometry: bool = True
    after_observed_at: datetime | None = None
    after_event_id: str | None = None


# --- statement building ----------------------------------------------------------------------------------


@dataclass(slots=True)
class Where:
    """Conditions and their bound values. Conditions are constants; values never are."""

    conditions: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    def add(self, condition: str, **params: Any) -> None:
        self.conditions.append(condition)
        self.params.update(params)

    def render(self) -> str:
        return "\n          AND ".join(self.conditions) if self.conditions else "true"


def escape_like(value: str) -> str:
    """Escape ``%``, ``_`` and the escape character, so a name search cannot become a wildcard."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _properties(properties: Sequence[Property], extra: Mapping[str, str] | None = None) -> str:
    pairs = [f"'{prop.key}', {prop.expression}" for prop in properties]
    pairs += [f"'{key}', {expression}" for key, expression in (extra or {}).items()]
    return f"jsonb_build_object({', '.join(pairs)})"


def _geometry(column: str, include_geometry: bool) -> str:
    if not include_geometry:
        return "NULL::jsonb"
    return f"public.ST_AsGeoJSON({column}, {GEOJSON_DECIMALS})::jsonb"


def _envelope() -> str:
    return (
        "public.ST_MakeEnvelope(CAST(:min_lon AS double precision), CAST(:min_lat AS double precision), "
        "CAST(:max_lon AS double precision), CAST(:max_lat AS double precision), 4326)"
    )


def add_bbox(where: Where, column: str, bbox: Bbox | None) -> None:
    if bbox is None:
        return
    min_lon, min_lat, max_lon, max_lat = bbox
    where.add(
        f"{column} OPERATOR(public.&&) {_envelope()}",
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
    )
    where.add(f"public.ST_Intersects({column}, {_envelope()})")


def _add_scope(where: Where, layer: SpatialLayer, release_id: uuid.UUID | None) -> None:
    if layer.scope == "release":
        if release_id is None:  # pragma: no cover - the service resolves the release first
            raise ValueError(f"{layer.code} needs a reference data release")
        where.add("t.release_id = CAST(:release_id AS uuid)", release_id=release_id)


def _add_filters(where: Where, layer: SpatialLayer, filters: Mapping[str, Any]) -> None:
    for name, value in filters.items():
        value_filter = layer.filter_named(name)
        if value_filter is None:
            raise UnsupportedFilterError(f"{layer.code} has no filter {name!r}")
        where.add(
            f"t.{value_filter.column} = CAST(:{value_filter.parameter} AS {value_filter.cast})",
            **{value_filter.parameter: value},
        )


def _add_period(where: Where, layer: SpatialLayer, at: datetime | None) -> None:
    if layer.period_column is None:
        return
    if at is None:  # pragma: no cover - the service defaults it to now
        raise ValueError(f"{layer.code} needs an instant for {layer.period_column}")
    where.add(f"t.{layer.period_column} @> CAST(:at AS timestamptz)", at=at)


def _add_name(where: Where, layer: SpatialLayer, name_contains: str | None) -> None:
    if name_contains is None:
        return
    if layer.name_column is None:  # pragma: no cover - the service rejects this first
        raise UnsupportedFilterError(f"{layer.code} has no name")
    where.add(
        f"t.{layer.name_column} ILIKE :name_pattern ESCAPE '\\'",
        name_pattern=f"%{escape_like(name_contains)}%",
    )


def _query_geometry_cte() -> str:
    return f"""
        WITH e AS MATERIALIZED (
            SELECT g.geom,
                   public.ST_Transform(g.geom, {METRIC_SRID}) AS geom_metric,
                   public.GeometryType(g.geom) = 'POINT' AS is_point
            FROM (SELECT public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326) AS geom) AS g
        )
    """  # noqa: S608 - a constant; the geometry is a bound parameter


def features_statement(query: FeatureQuery) -> tuple[str, dict[str, Any]]:
    layer = query.layer
    where = Where()
    _add_scope(where, layer, query.release_id)
    add_bbox(where, f"t.{layer.geometry_column}", query.bbox)
    _add_filters(where, layer, query.filters)
    _add_period(where, layer, query.at)
    _add_name(where, layer, query.name_contains)
    if query.after_id is not None:
        where.add(f"t.{layer.id_column} > CAST(:after_id AS uuid)", after_id=query.after_id)
    statement = f"""
        SELECT t.{layer.id_column} AS id,
               {_geometry(f"t.{layer.geometry_column}", query.include_geometry)} AS geometry,
               {_properties(layer.properties)} AS properties
        FROM {layer.table} AS t
        WHERE {where.render()}
        ORDER BY t.{layer.id_column}
        LIMIT CAST(:limit AS integer)
    """  # noqa: S608 - identifiers come from app.spatial.layers, values are bound parameters
    return statement, {**where.params, "limit": query.limit}


def distance_statement(query: DistanceQuery) -> tuple[str, dict[str, Any]]:
    layer = query.layer
    distance = layer.distance_to("e.geom_metric")
    radius = "CAST(:distance_m AS double precision)"
    where = Where()
    where.params["wkb"] = query.geometry_wkb
    _add_scope(where, layer, query.release_id)
    # The circumscribing search geometry feeds the index; the exact distance decides.
    where.add(
        f"t.{layer.metric_column} OPERATOR(public.&&) public.ST_Expand(e.geom_metric, {radius})",
        distance_m=query.distance_m,
    )
    where.add(f"public.ST_DWithin(t.{layer.metric_column}, e.geom_metric, {radius})")
    if not layer.knn_ordered:
        where.add(f"({distance}) <= {radius}")
    _add_filters(where, layer, query.filters)
    _add_period(where, layer, query.at)
    _add_name(where, layer, query.name_contains)
    if query.after_id is not None:
        after = "CAST(:after_distance_m AS double precision)"
        where.add(
            f"(({distance}) > {after} OR (({distance}) = {after} "
            f"AND t.{layer.id_column} > CAST(:after_id AS uuid)))",
            after_distance_m=query.after_distance_m,
            after_id=query.after_id,
        )
    order = (
        f"t.{layer.metric_column} OPERATOR(public.<->) e.geom_metric"
        if layer.knn_ordered
        else f"({distance})"
    )
    # The search runs as a lateral subquery over the one-row geometry, which is what lets PostgreSQL
    # drive it from the spatial index (a parameterised inner path) instead of scanning the table.
    statement = f"""
        {_query_geometry_cte()}
        SELECT f.id, f.geometry, f.properties, f.distance_m
        FROM e, LATERAL (
            SELECT t.{layer.id_column} AS id,
                   {_geometry(f"t.{layer.geometry_column}", query.include_geometry)} AS geometry,
                   {_properties(layer.properties)} AS properties,
                   ({distance}) AS distance_m
            FROM {layer.table} AS t
            WHERE {where.render()}
            ORDER BY {order}, t.{layer.id_column}
            LIMIT CAST(:limit AS integer)
        ) AS f
        ORDER BY f.distance_m, f.id
    """  # noqa: S608 - identifiers come from app.spatial.layers, values are bound parameters
    return statement, {**where.params, "limit": query.limit}


def containment_statement(query: ContainmentQuery) -> tuple[str, dict[str, Any]]:
    """Areas that cover (or intersect) the geometry.

    Candidates come from the index: the subdivided parts in ``ref.area_part`` for the reference area
    layers, the geometry's own bounding box otherwise. The exact test then runs on the whole feature, in
    EPSG:4326, boundary inclusive - except for circle and corridor geofences, whose exact shape is the
    definition plus its radius in EPSG:5235.
    """
    layer = query.layer
    geom = f"t.{layer.geometry_column}"
    covers = f"public.ST_Covers({geom}, e.geom)"
    where = Where()
    where.params["wkb"] = query.geometry_wkb
    _add_scope(where, layer, query.release_id)
    if layer.containment == "area_part":
        where.add(
            f"""t.{layer.id_column} IN (
                SELECT p.feature_id FROM ref.area_part AS p
                WHERE p.release_id = CAST(:release_id AS uuid) AND p.area_kind = CAST(:area_kind AS text)
                  AND public.ST_Intersects(p.geom, e.geom)
            )""",  # noqa: S608 - identifiers come from app.spatial.layers
            area_kind=layer.area_kind,
        )
        where.add(covers if query.covers else f"public.ST_Intersects({geom}, e.geom)")
    elif layer.containment == "geofence":
        where.add(f"t.{layer.metric_column} OPERATOR(public.&&) e.geom_metric")
        where.add(_geofence_containment(layer, geom, covers, covers_mode=query.covers))
    else:
        where.add(f"{geom} OPERATOR(public.&&) e.geom")
        where.add(covers if query.covers else f"public.ST_Intersects({geom}, e.geom)")
    _add_filters(where, layer, query.filters)
    _add_period(where, layer, query.at)
    _add_name(where, layer, query.name_contains)
    if query.after_id is not None:
        where.add(f"t.{layer.id_column} > CAST(:after_id AS uuid)", after_id=query.after_id)
    relation = "'within'" if query.covers else _relation_expression(layer, geom, covers)
    statement = f"""
        {_query_geometry_cte()}
        SELECT f.id, f.geometry, f.properties, f.relation
        FROM e, LATERAL (
            SELECT t.{layer.id_column} AS id,
                   {_geometry(geom, query.include_geometry)} AS geometry,
                   {_properties(layer.properties)} AS properties,
                   {relation} AS relation
            FROM {layer.table} AS t
            WHERE {where.render()}
            ORDER BY t.{layer.id_column}
            LIMIT CAST(:limit AS integer)
        ) AS f
        ORDER BY f.id
    """  # noqa: S608 - identifiers come from app.spatial.layers, values are bound parameters
    return statement, {**where.params, "limit": query.limit}


def _radius(layer: SpatialLayer) -> str:
    return f"t.{layer.radius_column}::double precision"


def _within_radius(layer: SpatialLayer) -> str:
    """A point at exactly the radius counts as inside: the test is the distance, not a polygon."""
    return f"public.ST_DWithin(t.definition_geom_metric, e.geom_metric, {_radius(layer)})"


def _covered_by_radius(layer: SpatialLayer) -> str:
    """Every point of a line or area lies within the radius of the definition.

    For a circle this is exact: the farthest point of the geometry from the centre (``ST_MaxDistance``,
    which is attained at a vertex) must be within the radius. For a corridor the centre line is buffered;
    a buffer is a polygon and therefore slightly inside the true shape, so it is drawn finely enough
    (``quad_segs`` = 512) that the deviation stays below the centimetre this API rounds to, even at
    the largest half-width.
    """
    buffered = f"public.ST_Buffer(t.definition_geom_metric, {_radius(layer)}, 'quad_segs={COVERS_QUAD_SEGS}')"
    return (
        "CASE WHEN public.GeometryType(t.definition_geom) = 'POINT' "
        f"THEN public.ST_MaxDistance(t.definition_geom_metric, e.geom_metric) <= {_radius(layer)} "
        f"ELSE public.ST_Covers({buffered}, e.geom_metric) END"
    )


def _geofence_inside(layer: SpatialLayer, covers: str) -> str:
    """Whether the geofence contains the whole geometry: polygons by their area, circles and corridors by
    their definition and radius."""
    return (
        f"CASE WHEN t.{layer.radius_column} IS NULL THEN {covers} "
        f"WHEN e.is_point THEN {_within_radius(layer)} "
        f"ELSE {_covered_by_radius(layer)} END"
    )


def _geofence_containment(layer: SpatialLayer, geom: str, covers: str, *, covers_mode: bool) -> str:
    if covers_mode:
        return _geofence_inside(layer, covers)
    return (
        f"CASE WHEN t.{layer.radius_column} IS NULL THEN public.ST_Intersects({geom}, e.geom) "
        f"ELSE {_within_radius(layer)} END"
    )


def _relation_expression(layer: SpatialLayer, geom: str, covers: str) -> str:
    """``within`` when the whole geometry lies inside the feature, else ``intersects`` (as in geo-context).

    Only needed in ``intersects`` mode: in ``covers`` mode the condition is the containment itself, so
    every row returned is ``within`` and the test is not repeated in the target list.
    """
    inside = _geofence_inside(layer, covers) if layer.containment == "geofence" else covers
    return f"CASE WHEN e.is_point OR {inside} THEN 'within' ELSE 'intersects' END"


def events_statement(query: EventQuery) -> tuple[str, dict[str, Any]]:
    where = Where()
    where.add(
        "t.observed_at >= CAST(:time_from AS timestamptz) AND t.observed_at < CAST(:time_to AS timestamptz)",
        time_from=query.time_from,
        time_to=query.time_to,
    )
    add_bbox(where, f"t.{EVENTS.geometry_column}", query.bbox)
    for name, value in query.filters.items():
        value_filter = next((f for f in EVENTS.filters if f.name == name), None)
        if value_filter is None:
            raise UnsupportedFilterError(f"events have no filter {name!r}")
        where.add(
            f"t.{value_filter.column} = CAST(:{value_filter.parameter} AS {value_filter.cast})",
            **{value_filter.parameter: value},
        )
    if query.geofence_id is not None:
        where.add(
            f"""EXISTS (
                SELECT 1 FROM {EVENTS.geofence_hit_table} AS h
                WHERE h.tenant_id = t.tenant_id AND h.event_id = t.event_id
                  AND h.observed_at = t.observed_at
                  AND h.geofence_id = CAST(:geofence_id AS uuid)
            )""",  # noqa: S608 - identifiers come from app.spatial.layers
            geofence_id=query.geofence_id,
        )
    if query.admin_area_id is not None:
        ids = " OR ".join(f"c.{column} = CAST(:admin_area_id AS uuid)" for column in EVENTS.admin_columns)
        where.add(f"({ids})", admin_area_id=query.admin_area_id)
    if query.admin_area_code is not None:
        codes = " OR ".join(
            f"c.{column.removesuffix('_id')}_code = CAST(:admin_area_code AS text)"
            for column in EVENTS.admin_columns
        )
        where.add(f"({codes})", admin_area_code=query.admin_area_code)
    if query.after_event_id is not None:
        where.add(
            "(t.observed_at < CAST(:after_observed_at AS timestamptz) "
            "OR (t.observed_at = CAST(:after_observed_at AS timestamptz) "
            'AND t.event_id COLLATE "C" < CAST(:after_event_id AS text)))',
            after_observed_at=query.after_observed_at,
            after_event_id=query.after_event_id,
        )
    admin = ", ".join(
        f"'l{index}', c.admin_l{index}_code" for index in range(1, len(EVENTS.admin_columns) + 1)
    )
    properties = _properties(
        EVENTS.properties,
        {"admin": f"jsonb_build_object({admin})", "refDataRelease": "c.release_code"},
    )
    statement = f"""
        SELECT t.event_id AS event_id, t.observed_at AS observed_at,
               {_geometry(f"t.{EVENTS.geometry_column}", query.include_geometry)} AS geometry,
               {properties} AS properties
        FROM {EVENTS.table} AS t
        LEFT JOIN {EVENTS.context_table} AS c
               ON c.tenant_id = t.tenant_id AND c.event_id = t.event_id AND c.observed_at = t.observed_at
        WHERE {where.render()}
        ORDER BY t.observed_at DESC, t.event_id COLLATE "C" DESC
        LIMIT CAST(:limit AS integer)
    """  # noqa: S608 - identifiers come from app.spatial.layers, values are bound parameters
    return statement, {**where.params, "limit": query.limit}


# --- fixed statements ------------------------------------------------------------------------------------

_RELEASE = text(
    """
    SELECT r.id, r.code, r.status
    FROM meta.ref_data_release AS r
    WHERE CASE WHEN CAST(:code AS text) IS NULL THEN r.is_current ELSE r.code = CAST(:code AS text) END
    """
).columns(id=UUID)

_LAYERS = text(
    """
    SELECT l.code, l.name, l.description, l.layer_group, l.geometry_types, l.srid, l.metric_srid,
           l.tenant_scoped, l.default_sharing_policy, l.update_frequency, l.nominal_accuracy_m
    FROM meta.layer AS l
    WHERE l.is_published
    ORDER BY l.layer_group COLLATE "C", l.code COLLATE "C"
    """
).columns(geometry_types=ARRAY(Text))

# Licence terms of the datasets a release holds, per layer, as they were when the data was loaded.
_DATASET_TERMS = text(
    """
    SELECT y.code AS layer, l.attribution, l.redistribution_allowed, s.code AS source
    FROM meta.dataset_load AS l
    JOIN meta.layer AS y ON y.id = l.layer_id
    JOIN meta.data_source AS s ON s.id = l.source_id
    WHERE l.release_id = :release_id AND l.status = 'completed'
    ORDER BY y.code COLLATE "C", s.code COLLATE "C", l.attribution COLLATE "C"
    """
).bindparams(bindparam("release_id", type_=UUID))


@dataclass(frozen=True, slots=True)
class DatasetTerms:
    """What the licence of one dataset of a release requires or forbids."""

    layer: str
    source: str
    attribution: str
    redistribution_allowed: bool


# Reverse geocoding: the administrative hierarchy at the point plus the nearest settlement and road.
# Reference data only - no tenant data is read, and nothing is stored.
REVERSE_LOOKUP_SQL: Final = """
    WITH p AS MATERIALIZED (
        SELECT g.geom, public.ST_Transform(g.geom, 5235) AS geom_metric
        FROM (SELECT public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326) AS geom) AS g
    )
    SELECT admin.items AS admin_areas, settlement.item AS settlement, road.item AS road,
           missing.items AS missing_layers
    FROM p

    LEFT JOIN LATERAL (
        SELECT coalesce(jsonb_agg(jsonb_build_object(
                   'id', a.id, 'code', a.code, 'name', a.name, 'nameSi', a.name_si, 'nameTa', a.name_ta,
                   'level', a.level, 'levelName', a.level_name
               ) ORDER BY a.level, a.code COLLATE "C"), '[]'::jsonb) AS items
        FROM ref.admin_area AS a
        WHERE a.id IN (
            SELECT part.feature_id FROM ref.area_part AS part
            WHERE part.release_id = CAST(:release_id AS uuid) AND part.area_kind = 'admin_area'
              AND public.ST_Intersects(part.geom, p.geom)
        )
    ) AS admin ON true

    LEFT JOIN LATERAL (
        SELECT jsonb_build_object(
                   'id', s.id, 'name', s.name, 'nameSi', s.name_si, 'nameTa', s.name_ta,
                   'settlementType', s.settlement_type, 'basis', s.geometry_basis,
                   'distanceM', public.ST_Distance(s.geom_metric, p.geom_metric)
               ) AS item
        FROM ref.settlement AS s
        WHERE s.release_id = CAST(:release_id AS uuid)
          AND public.ST_DWithin(s.geom_metric, p.geom_metric, CAST(:settlement_radius_m AS double precision))
        ORDER BY s.geom_metric OPERATOR(public.<->) p.geom_metric, s.id
        LIMIT 1
    ) AS settlement ON true

    LEFT JOIN LATERAL (
        SELECT jsonb_build_object(
                   'id', r.id, 'name', r.name, 'class', r.road_class, 'refCode', r.ref_code,
                   'distanceM', public.ST_Distance(r.geom_metric, p.geom_metric)
               ) AS item
        FROM ref.road AS r
        WHERE r.release_id = CAST(:release_id AS uuid)
          AND public.ST_DWithin(r.geom_metric, p.geom_metric, CAST(:road_radius_m AS double precision))
        ORDER BY r.geom_metric OPERATOR(public.<->) p.geom_metric, r.id
        LIMIT 1
    ) AS road ON true

    LEFT JOIN LATERAL (
        SELECT coalesce(jsonb_agg(l.name ORDER BY l.ord), '[]'::jsonb) AS items
        FROM (VALUES
            (1, 'admin_area', 'ref.admin_area'),
            (2, 'settlement', 'ref.settlement'),
            (3, 'road', 'ref.road'),
            (4, 'protected_area', 'ref.protected_area'),
            (5, 'risk_zone', 'ref.risk_zone')
        ) AS l(ord, name, layer_code)
        WHERE NOT EXISTS (
            SELECT 1
            FROM meta.dataset_load AS d
            JOIN meta.layer AS y ON y.id = d.layer_id
            WHERE d.release_id = CAST(:release_id AS uuid) AND y.code = l.layer_code
              AND d.status = 'completed' AND d.loaded_count > 0
        )
    ) AS missing ON true
"""
_REVERSE_LOOKUP = text(REVERSE_LOOKUP_SQL).columns(
    admin_areas=JSONB, settlement=JSONB, road=JSONB, missing_layers=JSONB
)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal | int | float) else None


class SpatialQueryRepository:
    """Read-only spatial queries. Tenant visibility comes from the transaction's tenant (row-level
    security); reference data comes from the release the caller asked for."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def release(self, code: str | None) -> ReleaseRow | None:
        row = (await self._session.execute(_RELEASE, {"code": code})).one_or_none()
        return None if row is None else ReleaseRow(as_uuid(row.id), row.code, row.status)

    async def dataset_terms(self, release_id: uuid.UUID) -> tuple[DatasetTerms, ...]:
        rows = (await self._session.execute(_DATASET_TERMS, {"release_id": release_id})).all()
        return tuple(
            DatasetTerms(row.layer, row.source, row.attribution, bool(row.redistribution_allowed))
            for row in rows
        )

    async def layers(self) -> tuple[LayerRow, ...]:
        rows = (await self._session.execute(_LAYERS)).all()
        return tuple(
            LayerRow(
                code=row.code,
                name=row.name,
                description=row.description,
                layer_group=row.layer_group,
                geometry_types=tuple(row.geometry_types),
                srid=int(row.srid),
                metric_srid=int(row.metric_srid),
                tenant_scoped=bool(row.tenant_scoped),
                default_sharing_policy=row.default_sharing_policy,
                update_frequency=row.update_frequency,
                nominal_accuracy_m=_number(row.nominal_accuracy_m),
            )
            for row in rows
        )

    async def features(self, query: FeatureQuery) -> tuple[FeatureRow, ...]:
        statement, params = features_statement(query)
        return await self._features(statement, params)

    async def within_distance(self, query: DistanceQuery) -> tuple[FeatureRow, ...]:
        statement, params = distance_statement(query)
        return await self._features(statement, params, distance=True)

    async def containing(self, query: ContainmentQuery) -> tuple[FeatureRow, ...]:
        statement, params = containment_statement(query)
        return await self._features(statement, params, relation=True)

    async def events(self, query: EventQuery) -> tuple[EventRow, ...]:
        statement, params = events_statement(query)
        rows = (
            await self._session.execute(text(statement).columns(geometry=JSONB, properties=JSONB), params)
        ).all()
        return tuple(
            EventRow(
                event_id=row.event_id,
                observed_at=row.observed_at,
                geometry=row.geometry,
                properties=dict(row.properties),
            )
            for row in rows
        )

    async def reverse(
        self, point_wkb: bytes, release_id: uuid.UUID, *, settlement_radius_m: float, road_radius_m: float
    ) -> ReverseRow:
        row = (
            await self._session.execute(
                _REVERSE_LOOKUP,
                {
                    "wkb": point_wkb,
                    "release_id": release_id,
                    "settlement_radius_m": settlement_radius_m,
                    "road_radius_m": road_radius_m,
                },
            )
        ).one()
        return ReverseRow(
            admin_areas=tuple(admin_row(item) for item in row.admin_areas),
            settlement=settlement_row(row.settlement),
            road=road_row(row.road),
            missing_layers=tuple(missing_layer(name) for name in row.missing_layers),
        )

    async def _features(
        self,
        statement: str,
        params: dict[str, Any],
        *,
        distance: bool = False,
        relation: bool = False,
    ) -> tuple[FeatureRow, ...]:
        rows = (
            await self._session.execute(
                text(statement).columns(id=UUID, geometry=JSONB, properties=JSONB), params
            )
        ).all()
        return tuple(
            FeatureRow(
                id=as_uuid(row.id),
                geometry=row.geometry,
                properties=dict(row.properties),
                distance_m=float(row.distance_m) if distance else None,
                relation=row.relation if relation else None,
            )
            for row in rows
        )
