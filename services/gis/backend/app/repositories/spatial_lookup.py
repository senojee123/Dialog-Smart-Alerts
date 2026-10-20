"""Spatial lookups that geo-context enrichment is built from.

Conventions (ARCHITECTURE.md, "Coordinate reference systems"):

* geometries are bound as 2D WKB and read with ``ST_GeomFromWKB(:wkb, 4326)``; nothing from a client
  is ever interpolated into SQL
* containment (admin areas, zones, polygon geofences, fields of view) is evaluated on the canonical
  EPSG:4326 geometry, boundary inclusive (``ST_Intersects`` / ``ST_Covers``)
* distances, radii and nearest-neighbour ordering use the stored EPSG:5235 columns; distance
  thresholds are inclusive (``ST_DWithin``)
* operational rows (devices, geofences) are subject to row-level security, so every lookup returns only
  what the tenant of the current transaction may see
* names and codes are ordered with the ``C`` collation, so results do not depend on the database locale
* tenant tables state the bounding-box test (``&&``) explicitly. Under row-level security PostgreSQL
  uses a condition for an index scan only if its operator is LEAKPROOF; ``ST_Intersects`` and
  ``ST_DWithin`` are not, the ``&&`` operator is once the database is initialised by
  ``db/init/20-gis-roles-and-databases.sh`` (readiness check ``tenant_spatial_indexes``)

All parts of a geo-context are computed by one statement (:data:`GEO_CONTEXT_LOOKUP_SQL`): one round trip
per event, and one snapshot, so a context never mixes data from before and after a concurrent change.
Each part is an index-driven subquery (GiST on the geometry columns, KNN ``<->`` for nearest searches).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import BYTEA, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.geo_context import (
    CONTEXT_REFERENCE_LAYERS,
    GeofenceKind,
    ReferenceLayerName,
    Relation,
    SettlementBasis,
    ZoneType,
)


@dataclass(frozen=True, slots=True)
class ReleaseRow:
    id: uuid.UUID
    code: str
    status: str


@dataclass(frozen=True, slots=True)
class AdminAreaRow:
    id: uuid.UUID
    code: str
    name: str
    name_si: str | None
    name_ta: str | None
    level: int
    level_name: str


@dataclass(frozen=True, slots=True)
class SettlementRow:
    id: uuid.UUID
    name: str
    name_si: str | None
    name_ta: str | None
    settlement_type: str
    basis: SettlementBasis
    distance_m: float


@dataclass(frozen=True, slots=True)
class RoadRow:
    id: uuid.UUID
    name: str | None
    road_class: str
    ref_code: str | None
    distance_m: float


@dataclass(frozen=True, slots=True)
class ZoneRow:
    zone_type: ZoneType
    id: uuid.UUID
    name: str
    category: str
    severity: int | None
    relation: Relation


@dataclass(frozen=True, slots=True)
class GeofenceHitRow:
    id: uuid.UUID
    name: str
    kind: GeofenceKind
    tenant_id: str
    version: int
    relation: Relation


@dataclass(frozen=True, slots=True)
class DeviceRow:
    id: uuid.UUID
    name: str
    device_type: str
    tenant_id: str
    distance_m: float
    in_field_of_view: bool | None


@dataclass(frozen=True, slots=True)
class ContextLookupQuery:
    """Everything the lookup statement needs. Radii are metres (inclusive)."""

    geometry_wkb: bytes
    reference_point_wkb: bytes
    observed_at: datetime
    release_code: str | None
    settlement_radius_m: float
    road_radius_m: float
    device_radius_m: float
    device_limit: int
    source_device_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ContextLookupResult:
    """Raw facts for one event. ``release`` is None when no (current) release matched."""

    release: ReleaseRow | None
    admin_areas: tuple[AdminAreaRow, ...]
    settlement: SettlementRow | None
    road: RoadRow | None
    zones: tuple[ZoneRow, ...]
    geofences: tuple[GeofenceHitRow, ...]
    devices: tuple[DeviceRow, ...]
    missing_layers: tuple[ReferenceLayerName, ...]


@dataclass(frozen=True, slots=True)
class EventDevice:
    """A device an event refers to, with the field of view in effect at the observation time."""

    id: uuid.UUID
    tenant_id: str
    status: str
    wkb: bytes
    field_of_view_id: uuid.UUID | None
    field_of_view_wkb: bytes | None


GEO_CONTEXT_LOOKUP_SQL: Final = """
    WITH e AS MATERIALIZED (
        SELECT g.geom,
               public.ST_GeomFromWKB(CAST(:reference_point_wkb AS bytea), 4326) AS reference_point,
               public.ST_Transform(g.geom, 5235) AS geom_metric,
               public.GeometryType(g.geom) = 'POINT' AS is_point
        FROM (SELECT public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326) AS geom) AS g
    ),
    rel AS MATERIALIZED (
        SELECT r.id, r.code, r.status
        FROM meta.ref_data_release AS r
        WHERE CASE WHEN CAST(:release_code AS text) IS NULL THEN r.is_current
                   ELSE r.code = CAST(:release_code AS text) END
    )
    SELECT rel.id AS release_id, rel.code AS release_code, rel.status AS release_status,
           admin.items AS admin_areas, settlement.item AS settlement, road.item AS road,
           zones.items AS zones, fences.items AS geofences, devices.items AS devices,
           missing.items AS missing_layers
    FROM e
    LEFT JOIN rel ON true

    -- Admin areas containing the reference point (subdivided parts, GiST (release_id, area_kind, geom)).
    LEFT JOIN LATERAL (
        SELECT coalesce(jsonb_agg(jsonb_build_object(
                   'id', a.id, 'code', a.code, 'name', a.name, 'nameSi', a.name_si, 'nameTa', a.name_ta,
                   'level', a.level, 'levelName', a.level_name
               ) ORDER BY a.level, a.code COLLATE "C"), '[]'::jsonb) AS items
        FROM ref.admin_area AS a
        WHERE a.id IN (
            SELECT p.feature_id FROM ref.area_part AS p
            WHERE p.release_id = rel.id AND p.area_kind = 'admin_area'
              AND public.ST_Intersects(p.geom, e.reference_point)
        )
    ) AS admin ON true

    -- Nearest settlement within the radius (KNN on GiST (release_id, geom_metric)).
    LEFT JOIN LATERAL (
        SELECT jsonb_build_object(
                   'id', s.id, 'name', s.name, 'nameSi', s.name_si, 'nameTa', s.name_ta,
                   'settlementType', s.settlement_type, 'basis', s.geometry_basis,
                   'distanceM', public.ST_Distance(s.geom_metric, e.geom_metric)
               ) AS item
        FROM ref.settlement AS s
        WHERE s.release_id = rel.id
          AND public.ST_DWithin(s.geom_metric, e.geom_metric, CAST(:settlement_radius_m AS double precision))
        ORDER BY s.geom_metric OPERATOR(public.<->) e.geom_metric, s.id
        LIMIT 1
    ) AS settlement ON true

    -- Nearest road within the radius.
    LEFT JOIN LATERAL (
        SELECT jsonb_build_object(
                   'id', r.id, 'name', r.name, 'class', r.road_class, 'refCode', r.ref_code,
                   'distanceM', public.ST_Distance(r.geom_metric, e.geom_metric)
               ) AS item
        FROM ref.road AS r
        WHERE r.release_id = rel.id
          AND public.ST_DWithin(r.geom_metric, e.geom_metric, CAST(:road_radius_m AS double precision))
        ORDER BY r.geom_metric OPERATOR(public.<->) e.geom_metric, r.id
        LIMIT 1
    ) AS road ON true

    -- Protected areas and risk zones: candidates from the subdivided parts, relation on the whole zone.
    LEFT JOIN LATERAL (
        SELECT coalesce(
                   jsonb_agg(z.item ORDER BY z.zone_type, z.name COLLATE "C", z.id), '[]'::jsonb
               ) AS items
        FROM (
            SELECT 'protected_area' AS zone_type, pa.id, pa.name,
                   jsonb_build_object(
                       'id', pa.id, 'type', 'protected_area', 'name', pa.name, 'category', pa.designation,
                       'severity', NULL,
                       'relation', CASE WHEN e.is_point OR public.ST_Covers(pa.geom, e.geom)
                                        THEN 'within' ELSE 'intersects' END
                   ) AS item
            FROM ref.protected_area AS pa
            WHERE pa.id IN (
                SELECT p.feature_id FROM ref.area_part AS p
                WHERE p.release_id = rel.id AND p.area_kind = 'protected_area'
                  AND public.ST_Intersects(p.geom, e.geom)
            )
            UNION ALL
            SELECT 'risk_zone', rz.id, rz.name,
                   jsonb_build_object(
                       'id', rz.id, 'type', 'risk_zone', 'name', rz.name, 'category', rz.risk_type,
                       'severity', rz.severity,
                       'relation', CASE WHEN e.is_point OR public.ST_Covers(rz.geom, e.geom)
                                        THEN 'within' ELSE 'intersects' END
                   )
            FROM ref.risk_zone AS rz
            WHERE rz.valid_during @> CAST(:observed_at AS timestamptz)
              AND rz.id IN (
                  SELECT p.feature_id FROM ref.area_part AS p
                  WHERE p.release_id = rel.id AND p.area_kind = 'risk_zone'
                    AND public.ST_Intersects(p.geom, e.geom)
              )
        ) AS z
    ) AS zones ON true

    -- Geofences active at the observation time and visible to the tenant (row-level security).
    -- Polygons: containment on the EPSG:4326 area. Circles and corridors: the circumscribing
    -- geom_metric feeds the index, the exact inclusive distance to the definition decides.
    LEFT JOIN LATERAL (
        SELECT coalesce(jsonb_agg(jsonb_build_object(
                   'id', h.id, 'name', h.name, 'kind', h.geofence_kind, 'tenantId', h.tenant_id,
                   'version', h.version, 'relation', h.relation
               ) ORDER BY h.name COLLATE "C", h.id), '[]'::jsonb) AS items
        FROM (
            SELECT g.id, g.name, g.geofence_kind, g.tenant_id, g.version,
                   CASE WHEN e.is_point OR public.ST_Covers(g.geom, e.geom)
                        THEN 'within' ELSE 'intersects' END AS relation
            FROM ops.geofence AS g
            WHERE g.geofence_kind = 'polygon'
              AND g.status = 'active'
              AND g.effective_during @> CAST(:observed_at AS timestamptz)
              AND g.geom OPERATOR(public.&&) e.geom
              AND public.ST_Intersects(g.geom, e.geom)
            UNION ALL
            SELECT g.id, g.name, g.geofence_kind, g.tenant_id, g.version,
                   CASE WHEN e.is_point OR public.ST_Covers(
                            public.ST_Buffer(
                                g.definition_geom_metric, g.radius_m::double precision, 'quad_segs=32'
                            ),
                            e.geom_metric
                        ) THEN 'within' ELSE 'intersects' END
            FROM ops.geofence AS g
            WHERE g.geofence_kind IN ('circle', 'corridor')
              AND g.status = 'active'
              AND g.effective_during @> CAST(:observed_at AS timestamptz)
              AND g.geom_metric OPERATOR(public.&&) e.geom_metric
              AND public.ST_DWithin(g.definition_geom_metric, e.geom_metric, g.radius_m::double precision)
        ) AS h
    ) AS fences ON true

    -- Nearest active devices visible to the tenant, without the reporting device; whether the event
    -- lies in each device's field of view at the observation time.
    LEFT JOIN LATERAL (
        SELECT coalesce(jsonb_agg(n.item ORDER BY n.distance_m, n.id), '[]'::jsonb) AS items
        FROM (
            SELECT d.id, public.ST_Distance(d.geom_metric, e.geom_metric) AS distance_m,
                   jsonb_build_object(
                       'deviceId', d.id, 'name', d.name, 'deviceType', d.device_type, 'tenantId', d.tenant_id,
                       'distanceM', public.ST_Distance(d.geom_metric, e.geom_metric),
                       'inFieldOfView', fov.hit
                   ) AS item
            FROM ops.device AS d
            LEFT JOIN LATERAL (
                SELECT public.ST_Intersects(f.geom, e.geom) AS hit
                FROM ops.device_field_of_view AS f
                WHERE f.device_id = d.id AND f.valid_during @> CAST(:observed_at AS timestamptz)
            ) AS fov ON true
            WHERE d.status = 'active'
              AND d.id IS DISTINCT FROM CAST(:source_device_id AS uuid)
              AND d.geom_metric OPERATOR(public.&&)
                  public.ST_Expand(e.geom_metric, CAST(:device_radius_m AS double precision))
              AND public.ST_DWithin(d.geom_metric, e.geom_metric, CAST(:device_radius_m AS double precision))
            ORDER BY d.geom_metric OPERATOR(public.<->) e.geom_metric, d.id
            LIMIT CAST(:device_limit AS integer)
        ) AS n
    ) AS devices ON true

    -- Reference layers without features in the release, from the lineage records: a completed load with
    -- loaded features (published releases are immutable, so the counts are final).
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
            WHERE d.release_id = rel.id AND y.code = l.layer_code
              AND d.status = 'completed' AND d.loaded_count > 0
        )
    ) AS missing ON true
"""
# Typed parameters, shared with EXPLAIN in the index-usage tests.
GEO_CONTEXT_LOOKUP_PARAMS: Final = (
    bindparam("wkb", type_=BYTEA),
    bindparam("reference_point_wkb", type_=BYTEA),
    bindparam("source_device_id", type_=UUID),
)
_GEO_CONTEXT_LOOKUP = (
    text(GEO_CONTEXT_LOOKUP_SQL)
    .bindparams(*GEO_CONTEXT_LOOKUP_PARAMS)
    .columns(
        release_id=UUID,
        admin_areas=JSONB,
        settlement=JSONB,
        road=JSONB,
        zones=JSONB,
        geofences=JSONB,
        devices=JSONB,
        missing_layers=JSONB,
    )
)

_EVENT_DEVICE = text(
    """
    SELECT d.id, d.tenant_id, d.status, public.ST_AsBinary(d.geom) AS wkb,
           f.id AS field_of_view_id, public.ST_AsBinary(f.geom) AS field_of_view_wkb
    FROM ops.device AS d
    LEFT JOIN ops.device_field_of_view AS f
           ON f.device_id = d.id
          AND f.valid_during @> CAST(:observed_at AS timestamptz)
          AND (CAST(:field_of_view_id AS uuid) IS NULL OR f.id = CAST(:field_of_view_id AS uuid))
    WHERE d.id = :device_id
    """
).bindparams(bindparam("device_id", type_=UUID), bindparam("field_of_view_id", type_=UUID))


def as_uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def admin_row(item: Mapping[str, Any]) -> AdminAreaRow:
    return AdminAreaRow(
        id=as_uuid(item["id"]),
        code=item["code"],
        name=item["name"],
        name_si=item["nameSi"],
        name_ta=item["nameTa"],
        level=int(item["level"]),
        level_name=item["levelName"],
    )


def settlement_row(item: Mapping[str, Any] | None) -> SettlementRow | None:
    if item is None:
        return None
    return SettlementRow(
        id=as_uuid(item["id"]),
        name=item["name"],
        name_si=item["nameSi"],
        name_ta=item["nameTa"],
        settlement_type=item["settlementType"],
        basis=item["basis"],
        distance_m=float(item["distanceM"]),
    )


def road_row(item: Mapping[str, Any] | None) -> RoadRow | None:
    if item is None:
        return None
    return RoadRow(
        id=as_uuid(item["id"]),
        name=item["name"],
        road_class=item["class"],
        ref_code=item["refCode"],
        distance_m=float(item["distanceM"]),
    )


def _zone(item: Mapping[str, Any]) -> ZoneRow:
    return ZoneRow(
        zone_type=item["type"],
        id=as_uuid(item["id"]),
        name=item["name"],
        category=item["category"],
        severity=_optional_int(item["severity"]),
        relation=item["relation"],
    )


def _geofence(item: Mapping[str, Any]) -> GeofenceHitRow:
    return GeofenceHitRow(
        id=as_uuid(item["id"]),
        name=item["name"],
        kind=item["kind"],
        tenant_id=item["tenantId"],
        version=int(item["version"]),
        relation=item["relation"],
    )


def _device(item: Mapping[str, Any]) -> DeviceRow:
    return DeviceRow(
        id=as_uuid(item["deviceId"]),
        name=item["name"],
        device_type=item["deviceType"],
        tenant_id=item["tenantId"],
        distance_m=float(item["distanceM"]),
        in_field_of_view=item["inFieldOfView"],
    )


def missing_layer(name: Any) -> ReferenceLayerName:
    if name not in CONTEXT_REFERENCE_LAYERS:
        raise ValueError(f"unexpected reference layer {name!r}")
    return cast(ReferenceLayerName, name)


class SpatialLookupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lookup_context(self, query: ContextLookupQuery) -> ContextLookupResult:
        """Resolve the release and compute every part of the geo-context in one statement."""
        row = (
            await self._session.execute(
                _GEO_CONTEXT_LOOKUP,
                {
                    "wkb": query.geometry_wkb,
                    "reference_point_wkb": query.reference_point_wkb,
                    "observed_at": query.observed_at,
                    "release_code": query.release_code,
                    "settlement_radius_m": query.settlement_radius_m,
                    "road_radius_m": query.road_radius_m,
                    "device_radius_m": query.device_radius_m,
                    "device_limit": query.device_limit,
                    "source_device_id": query.source_device_id,
                },
            )
        ).one()
        release = (
            None
            if row.release_id is None
            else ReleaseRow(as_uuid(row.release_id), row.release_code, row.release_status)
        )
        return ContextLookupResult(
            release=release,
            admin_areas=tuple(admin_row(item) for item in row.admin_areas),
            settlement=settlement_row(row.settlement),
            road=road_row(row.road),
            zones=tuple(_zone(item) for item in row.zones),
            geofences=tuple(_geofence(item) for item in row.geofences),
            devices=tuple(_device(item) for item in row.devices),
            missing_layers=tuple(missing_layer(name) for name in row.missing_layers),
        )

    async def event_device(
        self, device_id: uuid.UUID, observed_at: datetime, field_of_view_id: uuid.UUID | None = None
    ) -> EventDevice | None:
        """The device (if visible to the tenant) and its field of view at ``observed_at``.

        With ``field_of_view_id``, only that field of view is returned, and only if it was in effect.
        """
        row = (
            await self._session.execute(
                _EVENT_DEVICE,
                {"device_id": device_id, "observed_at": observed_at, "field_of_view_id": field_of_view_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return EventDevice(
            id=as_uuid(row.id),
            tenant_id=row.tenant_id,
            status=row.status,
            wkb=bytes(row.wkb),
            field_of_view_id=None if row.field_of_view_id is None else as_uuid(row.field_of_view_id),
            field_of_view_wkb=None if row.field_of_view_wkb is None else bytes(row.field_of_view_wkb),
        )
