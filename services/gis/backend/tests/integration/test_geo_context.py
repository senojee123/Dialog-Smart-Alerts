"""Geo-context enrichment end to end: service -> repositories -> PostGIS, with row-level security.

Expected answers come from the constructed fixture world (data/fixtures/synthetic_habarana) and, for
the open data, from independent computations with pyproj and Shapely.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pyproj import Geod
from shapely import LineString, Point, box
from sqlalchemy import text

from app.core.errors import CoordinateError, GisError, GisValidationError, InvalidGeometryError, NotFoundError
from app.core.tenancy import TenantId
from app.db.session import transaction
from app.schemas.events import EventLocationIn
from app.schemas.geo_context import GeoContext
from app.services.enrichment import GeoContextLimits, GeoContextService
from app.spatial.crs import to_metric, to_wgs84
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import (
    AUTHORITY,
    CENTRE,
    CIRCLE_RADIUS_M,
    OPEN_RELEASE,
    ROAD_LATITUDE,
    SYNTHETIC_RELEASE,
    TENANT_A,
    TENANT_B,
    point,
)

OBSERVED = datetime(2026, 9, 10, 4, 30, tzinfo=UTC)
_counter = iter(range(1, 1_000_000))


def service(world: SpatialWorld, **limits: Any) -> GeoContextService:
    return GeoContextService(world.app_sessions, world.service_area, GeoContextLimits(**limits))


def event(location: dict[str, Any] | None = None, **fields: Any) -> EventLocationIn:
    data: dict[str, Any] = {
        "eventId": f"evt-test-{next(_counter)}",
        "tenantId": TENANT_A.value,
        "observedAt": OBSERVED.isoformat(),
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": location,
    }
    data.update(fields)
    return EventLocationIn.model_validate(data)


def for_tenant(evt: EventLocationIn, tenant: TenantId) -> EventLocationIn:
    return evt.model_copy(update={"tenant_id": tenant.value})


async def enrich(world: SpatialWorld, tenant: TenantId, evt: EventLocationIn, **limits: Any) -> GeoContext:
    return await service(world, **limits).enrich(for_tenant(evt, tenant), release_code=SYNTHETIC_RELEASE)


# --- admin hierarchy and point-in-polygon ---------------------------------------------------------


async def test_point_inside_polygons_gets_full_admin_hierarchy(spatial_world: SpatialWorld) -> None:
    context = await enrich(spatial_world, TENANT_A, event(point(80.71, 8.00)))
    admin = context.admin
    assert admin.province is not None
    assert admin.province.code == "SYN-P1"
    assert admin.district is not None
    assert admin.district.code == "SYN-D1"
    assert admin.ds_division is not None
    assert admin.ds_division.code == "SYN-S1"
    assert admin.gn_division is not None
    assert admin.gn_division.code == "SYN-G1"
    assert admin.gn_division.level_name == "gn_division"
    assert admin.on_boundary is False
    assert context.ref_data_release == SYNTHETIC_RELEASE


async def test_point_outside_all_polygons_has_no_admin_areas(spatial_world: SpatialWorld) -> None:
    # Inside Sri Lanka and the service area, but outside the synthetic world.
    context = await enrich(spatial_world, TENANT_A, event(point(80.60, 7.90)))
    assert context.admin.province is None
    assert context.admin.district is None
    assert context.admin.on_boundary is False
    assert context.inside_zones == []


async def test_point_on_shared_boundary_is_flagged_and_resolved_deterministically(
    spatial_world: SpatialWorld,
) -> None:
    context = await enrich(spatial_world, TENANT_A, event(point(*CENTRE)))
    admin = context.admin
    assert admin.on_boundary is True
    # (80.75, 8.03) touches SYN-D1 and SYN-D2, and SYN-S1, SYN-S2 and SYN-S3: the lowest code wins.
    assert admin.district is not None
    assert admin.district.code == "SYN-D1"
    assert admin.ds_division is not None
    assert admin.ds_division.code == "SYN-S1"
    assert admin.gn_division is not None
    assert admin.gn_division.code == "SYN-G2"


async def test_boundary_vertex_and_edge_points_are_inside(spatial_world: SpatialWorld) -> None:
    corner = await enrich(spatial_world, TENANT_A, event(point(80.70, 7.98)))  # outer corner of the province
    edge = await enrich(spatial_world, TENANT_A, event(point(80.80, 8.05)))  # east edge of SYN-D2
    assert corner.admin.province is not None
    assert corner.admin.district is not None
    assert corner.admin.district.code == "SYN-D1"
    assert edge.admin.district is not None
    assert edge.admin.district.code == "SYN-D2"
    assert edge.admin.on_boundary is False


# --- zones ------------------------------------------------------------------------------------------


async def test_point_in_protected_area_and_in_its_enclave(spatial_world: SpatialWorld) -> None:
    inside = await enrich(spatial_world, TENANT_A, event(point(80.765, 8.045)))
    enclave = await enrich(spatial_world, TENANT_A, event(point(80.775, 8.055)))
    assert [(z.zone_type, z.name, z.relation) for z in inside.inside_zones] == [
        ("protected_area", "Fixture National Park", "within")
    ]
    assert enclave.inside_zones == []


async def test_line_and_area_events_report_within_or_intersects(spatial_world: SpatialWorld) -> None:
    crossing = event({"type": "LineString", "coordinates": [[80.75, 8.045], [80.765, 8.045]]})
    inside_area = event(
        {
            "type": "Polygon",
            "coordinates": [
                [[80.761, 8.041], [80.765, 8.041], [80.765, 8.045], [80.761, 8.045], [80.761, 8.041]]
            ],
        }
    )
    line_context = await enrich(spatial_world, TENANT_A, crossing)
    area_context = await enrich(spatial_world, TENANT_A, inside_area)
    assert line_context.geometry_kind == "line"
    assert area_context.geometry_kind == "area"
    assert [(z.name, z.relation) for z in line_context.inside_zones] == [
        ("Fixture National Park", "intersects")
    ]
    assert [(z.name, z.relation) for z in area_context.inside_zones] == [("Fixture National Park", "within")]


async def test_risk_zone_validity_period_is_respected(spatial_world: SpatialWorld) -> None:
    flood_point = point(80.71, 7.99)
    in_season = await enrich(
        spatial_world, TENANT_A, event(flood_point, observedAt="2025-11-15T06:00:00+05:30")
    )
    off_season = await enrich(
        spatial_world, TENANT_A, event(flood_point, observedAt="2026-03-01T06:00:00+05:30")
    )
    assert [(z.name, z.category, z.severity) for z in in_season.inside_zones] == [
        ("Fixture Flood Zone", "flood", 3)
    ]
    assert off_season.inside_zones == []


async def test_repaired_bow_tie_zone_is_usable(spatial_world: SpatialWorld) -> None:
    # The invalid bow-tie was repaired into a left and a right triangle meeting at (80.79, 7.99).
    in_right_triangle = await enrich(spatial_world, TENANT_A, event(point(80.793, 7.99)))
    between_triangles = await enrich(spatial_world, TENANT_A, event(point(80.790, 7.9865)))
    assert [z.name for z in in_right_triangle.inside_zones] == ["Fixture Bow-tie Reserve"]
    assert between_triangles.inside_zones == []


# --- proximity and thresholds ------------------------------------------------------------------------


async def test_nearest_settlement_and_road_distances_match_an_independent_computation(
    spatial_world: SpatialWorld,
) -> None:
    lon, lat = 80.71, 8.03
    context = await enrich(spatial_world, TENANT_A, event(point(lon, lat)))
    road = to_metric(LineString([(80.70, ROAD_LATITUDE), (80.80, ROAD_LATITUDE)]))
    town = to_metric(box(80.745, 8.025, 80.755, 8.035))
    here = to_metric(Point(lon, lat))
    assert context.nearest_road is not None
    assert context.nearest_road.name == "Fixture Road"
    assert context.nearest_road.road_class == "A"
    assert context.nearest_road.distance_m == pytest.approx(here.distance(road), abs=0.01)
    assert context.nearest_settlement is not None
    # Fixture Village (point at 80.71, 8.06) is about 3.3 km away; Fixture Town's footprint is ~3.8 km.
    village = to_metric(Point(80.71, 8.06))
    assert context.nearest_settlement.name == "Fixture Village"
    assert context.nearest_settlement.basis == "point"
    assert context.nearest_settlement.distance_m == pytest.approx(here.distance(village), abs=0.01)
    assert here.distance(town) > here.distance(village)


async def test_inside_a_settlement_footprint_the_distance_is_zero(spatial_world: SpatialWorld) -> None:
    context = await enrich(spatial_world, TENANT_A, event(point(80.752, 8.027)))
    assert context.nearest_settlement is not None
    assert context.nearest_settlement.name == "Fixture Town"
    assert context.nearest_settlement.basis == "footprint"
    assert context.nearest_settlement.distance_m == 0


async def test_distance_exactly_at_the_search_radius_is_included(spatial_world: SpatialWorld) -> None:
    """Search radii are inclusive: a feature exactly at the radius is found, one micrometre less is not."""
    location = point(80.71, 8.03)
    first = await enrich(spatial_world, TENANT_A, event(location))
    assert first.nearest_road is not None
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        exact = (
            await session.execute(
                text(
                    "SELECT public.ST_Distance(r.geom_metric, "
                    "public.ST_Transform(public.ST_SetSRID(public.ST_MakePoint(80.71, 8.03), 4326), 5235)) "
                    "FROM ref.road r WHERE r.id = :id"
                ),
                {"id": first.nearest_road.id},
            )
        ).scalar_one()
    at_radius = await enrich(spatial_world, TENANT_A, event(location), road_radius_m=exact)
    below_radius = await enrich(
        spatial_world, TENANT_A, event(location), road_radius_m=math.nextafter(exact, 0) - 1e-6
    )
    assert at_radius.nearest_road is not None
    assert at_radius.nearest_road.id == first.nearest_road.id
    assert below_radius.nearest_road is None


async def test_nearest_devices_respect_row_level_security(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    context = await enrich(spatial_world, TENANT_A, event(point(*CENTRE)))
    ids = [d.device_id for d in context.nearest_devices]
    assert ops.camera_b1 not in ids, "tenant B's private camera must be invisible to tenant A"
    assert ids[0] == ops.camera_b2_shared, "the shared camera of tenant B is the nearest visible device"
    assert set(ids) == {ops.camera_b2_shared, ops.camera_a1, ops.sensor_a2}
    distances = [d.distance_m for d in context.nearest_devices]
    assert distances == sorted(distances)
    assert context.nearest_devices[0].tenant_id == TENANT_B.value


# --- geofences ----------------------------------------------------------------------------------------


async def test_geofence_hits_for_the_owner(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    context = await enrich(spatial_world, TENANT_A, event(point(*CENTRE)))
    hits = {hit.id: hit for hit in context.geofence_hits}
    assert set(hits) == {ops.polygon_fence, ops.circle_fence}
    assert hits[ops.polygon_fence].relation == "within"
    assert hits[ops.circle_fence].kind == "circle"
    assert ops.archived_fence not in hits
    assert ops.future_fence not in hits


async def test_geofence_visibility_follows_sharing_policy(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    tenant_b = await enrich(spatial_world, TENANT_B, event(point(*CENTRE)))
    authority = await enrich(spatial_world, AUTHORITY, event(point(*CENTRE)))
    assert {h.id for h in tenant_b.geofence_hits} == {ops.b_private_fence, ops.b_authority_fence}
    assert {h.id for h in authority.geofence_hits} == {ops.b_authority_fence}


async def test_corridor_geofence_boundary(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    near = await enrich(spatial_world, TENANT_A, event(point(80.745, ROAD_LATITUDE + 0.0004)))  # ~44 m
    far = await enrich(spatial_world, TENANT_A, event(point(80.745, ROAD_LATITUDE + 0.0005)))  # ~55 m
    assert ops.corridor_fence in {h.id for h in near.geofence_hits}
    assert ops.corridor_fence not in {h.id for h in far.geofence_hits}


@pytest.mark.parametrize(
    ("geometry", "relation"),
    [
        (point(80.745, ROAD_LATITUDE + 0.0004), "within"),  # a point 44 m from the centre line
        ({"type": "LineString", "coordinates": [[80.74, 8.0102], [80.76, 8.0102]]}, "within"),  # 22 m off
        ({"type": "LineString", "coordinates": [[80.745, 8.0102], [80.745, 8.02]]}, "intersects"),
    ],
)
async def test_corridor_geofence_relation(
    spatial_world: SpatialWorld, geometry: dict[str, Any], relation: str
) -> None:
    context = await enrich(spatial_world, TENANT_A, event(geometry))
    hits = {hit.id: hit.relation for hit in context.geofence_hits}
    assert hits[spatial_world.ops.corridor_fence] == relation


async def test_area_event_larger_than_a_circle_geofence_only_intersects_it(
    spatial_world: SpatialWorld,
) -> None:
    around_centre = {
        "type": "Polygon",
        "coordinates": [[[80.74, 8.02], [80.76, 8.02], [80.76, 8.04], [80.74, 8.04], [80.74, 8.02]]],
    }
    context = await enrich(spatial_world, TENANT_A, event(around_centre))
    hits = {hit.id: hit.relation for hit in context.geofence_hits}
    assert hits[spatial_world.ops.circle_fence] == "intersects"
    assert hits[spatial_world.ops.polygon_fence] == "intersects"


async def test_geofence_hits_are_snapshots_that_do_not_pin_shared_geofences(
    spatial_world: SpatialWorld,
) -> None:
    ops = spatial_world.ops
    evt = event(point(80.71, 8.06))  # Fixture Village, inside tenant B's shared geofence
    context = await enrich(spatial_world, TENANT_A, evt)
    hit = next(h for h in context.geofence_hits if h.id == ops.b_shared_fence)
    assert (hit.tenant_id, hit.relation, hit.version) == (TENANT_B.value, "within", 1)
    async with transaction(spatial_world.app_sessions, TENANT_B) as session:
        deleted = await session.execute(
            text("DELETE FROM ops.geofence WHERE id = :id RETURNING id"), {"id": ops.b_shared_fence}
        )
        assert deleted.all() != [], "the owner can delete a geofence that other tenants have hits on"
        await session.rollback()
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        stored = await session.scalar(
            text(
                "SELECT geofence_tenant_id FROM geo.event_geofence_hit "
                "WHERE event_id = :id AND geofence_id = :g"
            ),
            {"id": evt.event_id, "g": ops.b_shared_fence},
        )
    assert stored == TENANT_B.value


@pytest.mark.parametrize(
    ("angle_deg", "offset_m", "expected"),
    [
        # Between two vertices the search polygon touches the circle: still a hit 1 cm inside.
        (1.40625, CIRCLE_RADIUS_M - 0.01, True),
        # At a vertex the search polygon reaches 500.15 m: the exact distance test decides.
        (0.0, CIRCLE_RADIUS_M - 0.01, True),
        (0.0, CIRCLE_RADIUS_M + 0.05, False),
    ],
)
async def test_circle_geofence_uses_the_exact_radius(
    spatial_world: SpatialWorld, angle_deg: float, offset_m: float, expected: bool
) -> None:
    ops = spatial_world.ops
    centre = to_metric(Point(*CENTRE))
    angle = math.radians(angle_deg)
    target = to_wgs84(Point(centre.x + offset_m * math.cos(angle), centre.y + offset_m * math.sin(angle)))
    context = await enrich(spatial_world, TENANT_A, event(point(target.x, target.y)))
    assert (ops.circle_fence in {h.id for h in context.geofence_hits}) is expected


# --- events: validation, device location, storage -------------------------------------------------------


@pytest.mark.parametrize(
    ("geometry", "error", "swapped"),
    [
        (point(8.03, 80.75), CoordinateError, True),  # [lat, lon]
        (point(80.27, 13.08), CoordinateError, False),  # Chennai, India
        (point(73.51, 4.17), CoordinateError, False),  # Malé, Maldives
        (
            {
                "type": "Polygon",
                "coordinates": [[[80.70, 8.0], [80.8, 8.1], [80.8, 8.0], [80.7, 8.1], [80.70, 8.0]]],
            },
            InvalidGeometryError,
            False,
        ),
    ],
)
async def test_unacceptable_locations_are_rejected_before_storage(
    spatial_world: SpatialWorld, geometry: dict[str, Any], error: type[GisError], swapped: bool
) -> None:
    evt = event(geometry)
    with pytest.raises(error) as info:
        await enrich(spatial_world, TENANT_A, evt)
    assert info.value.extensions.get("likelySwapped", False) is swapped
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        stored = await session.execute(
            text("SELECT count(*) FROM geo.event_location WHERE event_id = :id"), {"id": evt.event_id}
        )
        assert stored.scalar_one() == 0


@pytest.mark.parametrize(
    ("lon", "lat", "province"),
    [
        (80.670001, 7.279981, "Central Province"),  # Kandy
        (80.3833, 8.349993, "North Central Province"),  # Anuradhapura
        (81.233002, 8.568999, "Eastern Province"),  # Trincomalee
        (80.5895, 5.9235, None),  # Dondra Head, southern tip (coastline is generalised)
        (80.2346, 9.8167, None),  # Point Pedro, northern tip
    ],
)
async def test_sri_lankan_locations_are_accepted(
    spatial_world: SpatialWorld, lon: float, lat: float, province: str | None
) -> None:
    context = await service(spatial_world).enrich(event(point(lon, lat)))
    assert context.ref_data_release == OPEN_RELEASE
    if province is not None:
        assert context.admin.province is not None
        assert context.admin.province.name == province


async def test_device_position_and_field_of_view_are_used(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    evt = event(None, sourceType="device", locationSource="device", deviceId=str(ops.camera_a1))
    context = await enrich(spatial_world, TENANT_A, evt)
    assert context.location_source == "device"
    assert context.admin.gn_division is not None
    assert context.admin.gn_division.code == "SYN-G2"
    assert context.inside_zones[0].name == "Fixture Elephant Corridor"
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        row = (
            await session.execute(
                text(
                    "SELECT public.ST_AsText(geom) AS wkt, field_of_view_id, "
                    "public.ST_Equals(field_of_view, (SELECT geom FROM ops.device_field_of_view WHERE id = "
                    ":fov)) AS same_fov FROM geo.event_location WHERE event_id = :id"
                ),
                {"id": evt.event_id, "fov": ops.camera_a1_fov},
            )
        ).one()
    assert row.wkt == "POINT(80.745 8.01)"
    assert row.field_of_view_id == ops.camera_a1_fov
    assert row.same_fov is True


async def test_shared_devices_of_other_tenants_cannot_report_events(spatial_world: SpatialWorld) -> None:
    evt = event(
        None, sourceType="device", locationSource="device", deviceId=str(spatial_world.ops.camera_b2_shared)
    )
    with pytest.raises(GisValidationError, match="devices of the reporting tenant"):
        await enrich(spatial_world, TENANT_A, evt)


async def test_devices_of_other_tenants_cannot_be_referenced(spatial_world: SpatialWorld) -> None:
    evt = event(None, sourceType="device", locationSource="device", deviceId=str(spatial_world.ops.camera_b1))
    with pytest.raises(NotFoundError):
        await enrich(spatial_world, TENANT_A, evt)


async def test_context_is_stored_and_readable_only_by_the_owner(spatial_world: SpatialWorld) -> None:
    svc = service(spatial_world)
    evt = event(point(*CENTRE))
    computed = await svc.enrich(evt, release_code=SYNTHETIC_RELEASE)
    stored = await svc.get(TENANT_A, evt.event_id, evt.observed_at)
    assert stored == computed
    assert await svc.get(TENANT_B, evt.event_id, evt.observed_at) is None
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        row = (
            await session.execute(
                text(
                    "SELECT c.admin_l2_code, c.release_code, c.nearest_settlement_distance_m, "
                    "(SELECT count(*) FROM geo.event_geofence_hit h "
                    "WHERE h.event_id = c.event_id) AS fences, "
                    "(SELECT count(*) FROM geo.event_zone_hit z WHERE z.event_id = c.event_id) AS zones "
                    "FROM geo.event_geo_context c WHERE c.event_id = :id"
                ),
                {"id": evt.event_id},
            )
        ).one()
    assert (row.admin_l2_code, row.release_code, row.fences, row.zones) == (
        "SYN-D1",
        SYNTHETIC_RELEASE,
        2,
        0,
    )
    assert row.nearest_settlement_distance_m == 0


async def test_re_ingesting_an_event_replaces_location_and_context(spatial_world: SpatialWorld) -> None:
    svc = service(spatial_world)
    first = event(point(*CENTRE))
    moved = first.model_copy(update={"location": event(point(80.765, 8.045)).location})
    await svc.enrich(first, release_code=SYNTHETIC_RELEASE)
    context = await svc.enrich(moved, release_code=SYNTHETIC_RELEASE)
    assert [z.name for z in context.inside_zones] == ["Fixture National Park"]
    assert context.geofence_hits == []
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM geo.event_location WHERE event_id = :id) AS locations, "
                    "(SELECT count(*) FROM geo.event_geofence_hit WHERE event_id = :id) AS fences, "
                    "(SELECT count(*) FROM geo.event_zone_hit WHERE event_id = :id) AS zones"
                ),
                {"id": first.event_id},
            )
        ).one()
    assert tuple(counts) == (1, 0, 1)


async def test_recording_a_new_location_discards_the_old_context(spatial_world: SpatialWorld) -> None:
    svc = service(spatial_world)
    evt = event(point(*CENTRE))
    await svc.enrich(evt, release_code=SYNTHETIC_RELEASE)
    moved = evt.model_copy(update={"location": event(point(80.765, 8.045)).location})
    stored = await svc.record_location(moved)
    assert stored.geometry_kind == "point"
    assert await svc.get(TENANT_A, evt.event_id, evt.observed_at) is None
    context = await svc.recompute(TENANT_A, evt.event_id, evt.observed_at, release_code=SYNTHETIC_RELEASE)
    assert [z.name for z in context.inside_zones] == ["Fixture National Park"]


async def test_recompute_against_another_release(spatial_world: SpatialWorld) -> None:
    svc = service(spatial_world, settlement_radius_m=100_000)
    habarana = event(point(80.749, 8.037))
    synthetic = await svc.enrich(habarana, release_code=SYNTHETIC_RELEASE)
    real = await svc.recompute(TENANT_A, habarana.event_id, habarana.observed_at)
    assert synthetic.admin.district is not None
    assert synthetic.admin.district.code == "SYN-D1"
    assert real.ref_data_release == OPEN_RELEASE
    assert real.admin.province is not None
    assert real.admin.province.name == "North Central Province"
    assert real.admin.district is not None
    assert real.admin.district.name == "Anuradhapura District"
    assert real.admin.ds_division is not None
    assert real.admin.ds_division.name == "Palugaswewa"
    assert real.admin.gn_division is not None
    assert real.admin.gn_division.name == "Habarana"
    assert real.nearest_settlement is not None
    assert real.nearest_settlement.name == "Anuradhapura"
    geodesic = Geod(ellps="WGS84").inv(80.749, 8.037, 80.3833, 8.349993)[2]
    assert real.nearest_settlement.distance_m == pytest.approx(geodesic, rel=5e-4)
    assert await svc.get(TENANT_A, habarana.event_id, habarana.observed_at) == real


async def test_unpublished_and_unknown_releases_are_refused(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        await session.execute(text("INSERT INTO meta.ref_data_release (code) VALUES ('ref-2026.10-draft')"))
    with pytest.raises(GisValidationError, match="draft"):
        await service(spatial_world).enrich(event(point(*CENTRE)), release_code="ref-2026.10-draft")
    with pytest.raises(NotFoundError):
        await service(spatial_world).enrich(event(point(*CENTRE)), release_code="ref-1999.01")


async def _missing_recent_month(world: SpatialWorld) -> datetime:
    """A month in the on-demand window (the last 12 months) that has no partition yet."""
    async with transaction(world.migrator_sessions) as session:
        existing = set(
            (
                await session.execute(
                    text("SELECT substring(relname from '_p([0-9]{6})$') FROM pg_class WHERE relname ~ :p"),
                    {"p": "^event_location_p[0-9]{6}$"},
                )
            ).scalars()
        )
    today = datetime.now(UTC)
    for back in range(2, 12):
        year, month = divmod(today.year * 12 + today.month - 1 - back, 12)
        candidate = datetime(year, month + 1, 15, 8, 0, tzinfo=UTC)
        if candidate.strftime("%Y%m") not in existing:
            return candidate
    raise AssertionError("every recent month already has a partition")


async def test_missing_recent_month_partition_is_created_on_demand(spatial_world: SpatialWorld) -> None:
    moment = await _missing_recent_month(spatial_world)
    context = await enrich(spatial_world, TENANT_A, event(point(*CENTRE), observedAt=moment.isoformat()))
    assert context.observed_at == moment
    async with transaction(spatial_world.migrator_sessions) as session:
        partitions = await session.scalar(
            text("SELECT count(*) FROM pg_class WHERE relname ~ :pattern AND relkind = 'r'"),
            {"pattern": f"^event_.*_p{moment:%Y%m}$"},
        )
    assert partitions == 4


async def test_old_months_must_be_prepared_by_an_operator(spatial_world: SpatialWorld) -> None:
    old = event(point(*CENTRE), observedAt="2003-02-14T08:00:00+05:30")
    with pytest.raises(GisValidationError, match="too old"):
        await enrich(spatial_world, TENANT_A, old)
    async with transaction(spatial_world.migrator_sessions) as session:
        prepared = (
            (
                await session.execute(
                    text("SELECT geo.prepare_event_partitions(:start, :end)"),
                    {"start": datetime(2003, 1, 1, tzinfo=UTC), "end": datetime(2003, 3, 1, tzinfo=UTC)},
                )
            )
            .scalars()
            .all()
        )
    assert prepared == ["200301", "200302", "200303"]
    context = await enrich(spatial_world, TENANT_A, old)
    assert context.observed_at == datetime(2003, 2, 14, 2, 30, tzinfo=UTC)


@pytest.mark.parametrize("ahead", [timedelta(days=2), timedelta(days=90)])
async def test_events_in_the_future_are_refused(spatial_world: SpatialWorld, ahead: timedelta) -> None:
    future = event(point(*CENTRE), observedAt=(datetime.now(UTC) + ahead).isoformat())
    with pytest.raises(GisValidationError, match="future"):
        await enrich(spatial_world, TENANT_A, future)


async def test_small_clock_skew_is_tolerated(spatial_world: SpatialWorld) -> None:
    moment = datetime.now(UTC) + timedelta(hours=6)
    context = await enrich(spatial_world, TENANT_A, event(point(*CENTRE), observedAt=moment.isoformat()))
    assert context.observed_at == moment


async def test_without_tenant_nothing_is_visible(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.app_sessions) as session:
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM ops.device) AS devices, "
                    "(SELECT count(*) FROM ops.geofence) AS fences, "
                    "(SELECT count(*) FROM geo.event_location) AS events, "
                    "(SELECT count(*) FROM ref.admin_area) AS areas"
                )
            )
        ).one()
    assert (counts.devices, counts.fences, counts.events) == (0, 0, 0)
    assert counts.areas > 0, "reference data is not tenant-scoped"
