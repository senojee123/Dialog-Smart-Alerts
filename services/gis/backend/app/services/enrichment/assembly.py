"""Pure functions that turn lookup results into a ``geo-context/1`` document.

No I/O and no clock: the same inputs always give the same document, which is what makes enrichment
deterministic and easy to test.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import shapely

from app.repositories.events import GeoContextRecord, StoredEventLocation
from app.repositories.spatial_lookup import (
    AdminAreaRow,
    ContextLookupResult,
    ReleaseRow,
    RoadRow,
    SettlementRow,
)
from app.schemas.geo_context import (
    AdminAreaRef,
    AdminCodes,
    AdminHierarchy,
    GeoContext,
    GeofenceHit,
    NearbyDevice,
    NearestRoad,
    NearestSettlement,
    SearchLimits,
    ZoneHit,
)

DISTANCE_DECIMALS: Final = 2
MAX_SEARCH_RADIUS_M: Final = 100_000.0
MAX_DEVICE_LIMIT: Final = 50


@dataclass(frozen=True, slots=True)
class GeoContextLimits:
    """Search radii (metres, inclusive) and result sizes for the proximity parts of the context."""

    settlement_radius_m: float = 25_000.0
    road_radius_m: float = 10_000.0
    device_radius_m: float = 5_000.0
    device_limit: int = 5

    def __post_init__(self) -> None:
        radii = (self.settlement_radius_m, self.road_radius_m, self.device_radius_m)
        if any(not (0 < radius <= MAX_SEARCH_RADIUS_M) for radius in radii):
            raise ValueError(f"search radii must be in (0, {MAX_SEARCH_RADIUS_M:.0f}] metres")
        if not 0 <= self.device_limit <= MAX_DEVICE_LIMIT:
            raise ValueError(f"device_limit must be between 0 and {MAX_DEVICE_LIMIT}")

    def as_schema(self) -> SearchLimits:
        return SearchLimits(
            settlement_radius_m=self.settlement_radius_m,
            road_radius_m=self.road_radius_m,
            device_radius_m=self.device_radius_m,
            device_limit=self.device_limit,
        )


def metres(value: float) -> float:
    """Distances in documents: metres rounded to 0.01 m."""
    return round(value, DISTANCE_DECIMALS)


def reference_point_wkb(geometry_wkb: bytes) -> bytes:
    """Where the admin hierarchy is looked up: the point itself, else a point on the geometry."""
    geometry = shapely.from_wkb(geometry_wkb)
    point = geometry if geometry.geom_type == "Point" else shapely.point_on_surface(geometry)
    return bytes(shapely.to_wkb(point, output_dimension=2))


def _admin_ref(row: AdminAreaRow) -> AdminAreaRef:
    return AdminAreaRef(
        id=row.id,
        code=row.code,
        name=row.name,
        name_si=row.name_si,
        name_ta=row.name_ta,
        level=row.level,
        level_name=row.level_name,
    )


def build_admin_hierarchy(rows: Iterable[AdminAreaRow]) -> AdminHierarchy:
    """One area per level (1-4); on a shared boundary the lowest code wins and ``on_boundary`` is set.

    Codes are compared by code point, which matches the database's ``C`` collation ordering.
    """
    by_level: dict[int, list[AdminAreaRow]] = defaultdict(list)
    for row in rows:
        if 1 <= row.level <= 4:
            by_level[row.level].append(row)
    chosen = {level: _admin_ref(min(found, key=lambda r: r.code)) for level, found in by_level.items()}
    return AdminHierarchy(
        province=chosen.get(1),
        district=chosen.get(2),
        ds_division=chosen.get(3),
        gn_division=chosen.get(4),
        codes=AdminCodes(
            l1=_code(chosen.get(1)), l2=_code(chosen.get(2)), l3=_code(chosen.get(3)), l4=_code(chosen.get(4))
        ),
        on_boundary=any(len(found) > 1 for found in by_level.values()),
    )


def nearest_settlement_of(row: SettlementRow | None) -> NearestSettlement | None:
    """The nearest-settlement member; shared with reverse geocoding, so both say the same thing."""
    if row is None:
        return None
    return NearestSettlement(
        id=row.id,
        name=row.name,
        name_si=row.name_si,
        name_ta=row.name_ta,
        settlement_type=row.settlement_type,
        basis=row.basis,
        distance_m=metres(row.distance_m),
    )


def nearest_road_of(row: RoadRow | None) -> NearestRoad | None:
    if row is None:
        return None
    return NearestRoad(
        id=row.id,
        name=row.name,
        road_class=row.road_class,
        ref_code=row.ref_code,
        distance_m=metres(row.distance_m),
    )


def _code(area: AdminAreaRef | None) -> str | None:
    return None if area is None else area.code


def _id(area: AdminAreaRef | None) -> uuid.UUID | None:
    return None if area is None else area.id


def assemble_geo_context(
    location: StoredEventLocation,
    lookup: ContextLookupResult,
    release: ReleaseRow,
    limits: GeoContextLimits,
    computed_at: datetime,
) -> GeoContext:
    return GeoContext(
        event_id=location.event_id,
        tenant_id=location.tenant_id,
        observed_at=location.observed_at,
        location_source=location.location_source,
        geometry_kind=location.geometry_kind,
        admin=build_admin_hierarchy(lookup.admin_areas),
        nearest_settlement=nearest_settlement_of(lookup.settlement),
        nearest_road=nearest_road_of(lookup.road),
        inside_zones=[
            ZoneHit(
                id=zone.id,
                zone_type=zone.zone_type,
                name=zone.name,
                category=zone.category,
                severity=zone.severity,
                relation=zone.relation,
            )
            for zone in lookup.zones
        ],
        geofence_hits=[
            GeofenceHit(
                id=hit.id,
                name=hit.name,
                kind=hit.kind,
                tenant_id=hit.tenant_id,
                version=hit.version,
                relation=hit.relation,
            )
            for hit in lookup.geofences
        ],
        nearest_devices=[
            NearbyDevice(
                device_id=device.id,
                name=device.name,
                device_type=device.device_type,
                tenant_id=device.tenant_id,
                distance_m=metres(device.distance_m),
                in_field_of_view=device.in_field_of_view,
            )
            for device in lookup.devices
        ],
        missing_layers=list(lookup.missing_layers),
        search=limits.as_schema(),
        ref_data_release=release.code,
        computed_at=computed_at,
    )


def geo_context_record(context: GeoContext, release: ReleaseRow) -> GeoContextRecord:
    """The row stored for a context: the document plus the columns that are filtered on."""
    admin = context.admin
    settlement, road = context.nearest_settlement, context.nearest_road
    return GeoContextRecord(
        event_id=context.event_id,
        observed_at=context.observed_at,
        schema_version=context.schema_id,
        release_id=release.id,
        release_code=release.code,
        computed_at=context.computed_at,
        location_source=context.location_source,
        admin_ids=(_id(admin.province), _id(admin.district), _id(admin.ds_division), _id(admin.gn_division)),
        admin_codes=(admin.codes.l1, admin.codes.l2, admin.codes.l3, admin.codes.l4),
        nearest_settlement_id=None if settlement is None else settlement.id,
        nearest_settlement_distance_m=None if settlement is None else settlement.distance_m,
        nearest_road_id=None if road is None else road.id,
        nearest_road_distance_m=None if road is None else road.distance_m,
        document=context.model_dump(mode="json", by_alias=True),
        zone_hits=tuple((zone.zone_type, zone.id, zone.relation) for zone in context.inside_zones),
        geofence_hits=tuple(
            (hit.id, hit.tenant_id, hit.version, hit.relation) for hit in context.geofence_hits
        ),
    )
