"""The enrichment engine against PostGIS: the cases of the enrichment specification.

Normal event, protected areas, geofences, settlements, roads, several and no zones, boundaries and the
499 / 500 / 501 m cases around a 500 m threshold, invalid coordinates, tenant isolation, missing reference
data, determinism and the number of database round trips.

Expected values come from the constructed fixture world (``data/fixtures/synthetic_habarana``). Positions
at an exact distance are found by bisection with the database's own EPSG:5235 transformation, so the
distance PostGIS computes during enrichment is the distance the test intends.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import text

from app.core.errors import CoordinateError, GisError, InvalidGeometryError
from app.core.tenancy import TenantId
from app.db.session import transaction
from app.repositories.events import UnknownTenantError
from app.schemas.events import EventLocationIn
from app.schemas.geo_context import GeoContext
from app.services.enrichment import (
    GeoContextLimits,
    GeoContextService,
    ReferenceDataUnavailableError,
    ReleaseNotFoundError,
)
from app.services.reference_qa import ReferenceQa
from tests.integration.conftest import SpatialWorld
from tests.integration.distances import distance_to, latitude_at_distance
from tests.integration.spatial_world import (
    AUTHORITY,
    CENTRE,
    OPEN_RELEASE,
    ROAD_LATITUDE,
    SYNTHETIC_RELEASE,
    TENANT_A,
    TENANT_B,
    point,
)

OBSERVED: Final = datetime(2026, 9, 10, 4, 30, tzinfo=UTC)
FIXED_CLOCK: Final = datetime(2026, 9, 10, 4, 31, 5, 250000, tzinfo=UTC)
TENANT_C: Final = TenantId("fixture-tenant-c")
THRESHOLD_M: Final = 500.0
# Tenant C's lone camera, and the circle geofence around it, in the north-west of the fixture world.
THRESHOLD_SITE: Final = (80.715, 8.070)
VILLAGE: Final = (80.71, 8.06)
ROAD_PROBE_LON: Final = 80.72
MULTI_ZONE_POINT: Final = (80.758, 8.015)

_ids = iter(range(1, 1_000_000))


def event(location: dict[str, Any] | None, *, tenant: TenantId = TENANT_A, **fields: Any) -> EventLocationIn:
    data: dict[str, Any] = {
        "eventId": f"evt-engine-{next(_ids)}",
        "tenantId": tenant.value,
        "observedAt": OBSERVED.isoformat(),
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": location,
    }
    data.update(fields)
    return EventLocationIn.model_validate(data)


def engine(
    world: SpatialWorld, clock: Callable[[], datetime] | None = None, **limits: Any
) -> GeoContextService:
    options: dict[str, Any] = {} if clock is None else {"clock": clock}
    return GeoContextService(world.app_sessions, world.service_area, GeoContextLimits(**limits), **options)


async def enrich(world: SpatialWorld, evt: EventLocationIn, **limits: Any) -> GeoContext:
    return await engine(world, **limits).enrich(evt, release_code=SYNTHETIC_RELEASE)


# --- exact distances ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ThresholdWorld:
    camera: uuid.UUID
    fence: uuid.UUID
    positions: dict[tuple[str, float], tuple[float, float]]
    exact: dict[tuple[str, float], float]


@pytest.fixture(scope="module")
async def thresholds(spatial_world: SpatialWorld) -> ThresholdWorld:
    world = spatial_world
    async with transaction(world.migrator_sessions) as session:
        await session.execute(
            text(
                "INSERT INTO meta.tenant (tenant_id, name, kind) "
                "VALUES (:t, 'Fixture Tenant C', 'organisation')"
            ),
            {"t": TENANT_C.value},
        )
    lon, lat = THRESHOLD_SITE
    async with transaction(world.app_sessions, TENANT_C) as session:
        camera = await session.scalar(
            text(
                "INSERT INTO ops.device (name, external_id, device_type, geom, position_source) "
                "VALUES ('Fixture Camera C1', 'C1', 'camera', "
                "public.ST_SetSRID(public.ST_MakePoint(:lon, :lat), 4326), 'gps') RETURNING id"
            ),
            {"lon": lon, "lat": lat},
        )
        fence = await session.scalar(
            text(
                "INSERT INTO ops.geofence (name, geofence_kind, definition_geom, radius_m, status, "
                "effective_during) VALUES ('Fixture Threshold Fence', 'circle', "
                "public.ST_SetSRID(public.ST_MakePoint(:lon, :lat), 4326), :radius, 'active', "
                "tstzrange('2025-01-01', NULL)) RETURNING id"
            ),
            {"lon": lon, "lat": lat, "radius": THRESHOLD_M},
        )
        targets = {
            "device": (
                await session.scalar(
                    text("SELECT public.ST_AsEWKB(geom_metric) FROM ops.device WHERE id = :id"),
                    {"id": camera},
                ),
                lon,
                lat,
            ),
            "circle_geofence": (
                await session.scalar(
                    text("SELECT public.ST_AsEWKB(definition_geom_metric) FROM ops.geofence WHERE id = :id"),
                    {"id": fence},
                ),
                lon,
                lat,
            ),
        }
    async with transaction(world.app_sessions) as session:
        release = {"code": SYNTHETIC_RELEASE}
        targets["settlement"] = (
            await session.scalar(
                text(
                    "SELECT public.ST_AsEWKB(s.geom_metric) FROM ref.settlement s "
                    "JOIN meta.ref_data_release r ON r.id = s.release_id "
                    "WHERE r.code = :code AND s.name = 'Fixture Village'"
                ),
                release,
            ),
            VILLAGE[0],
            VILLAGE[1],
        )
        targets["road"] = (
            await session.scalar(
                text(
                    "SELECT public.ST_AsEWKB(x.geom_metric) FROM ref.road x "
                    "JOIN meta.ref_data_release r ON r.id = x.release_id "
                    "WHERE r.code = :code AND x.name = 'Fixture Road'"
                ),
                release,
            ),
            ROAD_PROBE_LON,
            ROAD_LATITUDE,
        )
        positions: dict[tuple[str, float], tuple[float, float]] = {}
        exact: dict[tuple[str, float], float] = {}
        for layer, (ewkb, target_lon, target_lat) in targets.items():
            for metres in (THRESHOLD_M - 1, THRESHOLD_M, THRESHOLD_M + 1):
                found = await latitude_at_distance(
                    session, bytes(ewkb), target_lon, target_lat, target_lat + 0.01, metres
                )
                positions[layer, metres] = (target_lon, found)
                exact[layer, metres] = await distance_to(session, bytes(ewkb), target_lon, found)
    return ThresholdWorld(
        camera=uuid.UUID(str(camera)), fence=uuid.UUID(str(fence)), positions=positions, exact=exact
    )


# --- normal event ----------------------------------------------------------------------------------------


async def test_normal_event_gets_a_complete_context(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    evt = event(point(80.7505, 8.0305), locationAccuracyM=15, metadata={"confidence": 0.9})
    context = await engine(spatial_world, clock=lambda: FIXED_CLOCK).enrich(
        evt, release_code=SYNTHETIC_RELEASE
    )

    assert (context.schema_id, context.event_id, context.tenant_id) == (
        "geo-context/1",
        evt.event_id,
        "fixture-tenant-a",
    )
    assert (context.location_source, context.geometry_kind) == ("sensor", "point")
    assert (context.ref_data_release, context.computed_at, context.observed_at) == (
        SYNTHETIC_RELEASE,
        FIXED_CLOCK,
        OBSERVED,
    )
    admin = context.admin
    assert admin.codes.model_dump() == {"l1": "SYN-P1", "l2": "SYN-D2", "l3": "SYN-S3", "l4": None}
    assert admin.province is not None
    assert admin.province.name == "Fixture Province"
    assert admin.on_boundary is False
    assert context.nearest_settlement is not None
    assert (context.nearest_settlement.name, context.nearest_settlement.distance_m) == ("Fixture Town", 0)
    assert context.nearest_road is not None
    assert context.nearest_road.name == "Fixture Road"
    assert context.inside_zones == []
    assert {hit.id for hit in context.geofence_hits} == {ops.polygon_fence, ops.circle_fence}
    assert [device.device_id for device in context.nearest_devices][:1] == [ops.camera_b2_shared]
    assert context.missing_layers == []
    assert context.search.model_dump() == {
        "settlement_radius_m": 25_000.0,
        "road_radius_m": 10_000.0,
        "device_radius_m": 5_000.0,
        "device_limit": 5,
    }
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        stored = (
            await session.execute(
                text(
                    "SELECT l.attributes, l.location_accuracy_m, c.document, c.release_code "
                    "FROM geo.event_location l "
                    "JOIN geo.event_geo_context c USING (tenant_id, event_id, observed_at) "
                    "WHERE l.event_id = :id"
                ),
                {"id": evt.event_id},
            )
        ).one()
    assert stored.attributes == {"confidence": 0.9}
    assert float(stored.location_accuracy_m) == 15
    assert stored.document == context.model_dump(mode="json", by_alias=True)
    assert stored.release_code == SYNTHETIC_RELEASE


async def test_enrichment_is_deterministic(spatial_world: SpatialWorld) -> None:
    svc = engine(spatial_world, clock=lambda: FIXED_CLOCK)
    first = event(point(*MULTI_ZONE_POINT))
    twin = first.model_copy(update={"event_id": "evt-engine-twin"})
    runs = [await svc.enrich(first, release_code=SYNTHETIC_RELEASE) for _ in range(3)]
    other = await svc.enrich(twin, release_code=SYNTHETIC_RELEASE)
    assert runs[0] == runs[1] == runs[2]
    assert runs[0].model_dump(exclude={"event_id"}) == other.model_dump(exclude={"event_id"})
    assert await svc.get(TENANT_A, first.event_id, first.observed_at) == runs[0]


# --- protected areas and zones ---------------------------------------------------------------------------


async def test_event_inside_a_protected_area(spatial_world: SpatialWorld) -> None:
    context = await enrich(spatial_world, event(point(80.785, 8.065)))
    assert [(z.zone_type, z.name, z.category, z.severity, z.relation) for z in context.inside_zones] == [
        ("protected_area", "Fixture National Park", "National Park", None, "within")
    ]


async def test_event_inside_several_zones(spatial_world: SpatialWorld) -> None:
    context = await enrich(spatial_world, event(point(*MULTI_ZONE_POINT)))
    assert [(z.zone_type, z.name, z.category, z.severity) for z in context.inside_zones] == [
        ("protected_area", "Fixture Sanctuary", "Sanctuary", None),
        ("risk_zone", "Fixture Drought Zone", "drought", 2),
        ("risk_zone", "Fixture Elephant Corridor", "elephant_corridor", 4),
    ]
    assert {z.relation for z in context.inside_zones} == {"within"}
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        stored = await session.scalar(
            text("SELECT count(*) FROM geo.event_zone_hit WHERE event_id = :id"), {"id": context.event_id}
        )
    assert stored == 3


async def test_area_event_across_several_zones_intersects_them(spatial_world: SpatialWorld) -> None:
    area = {
        "type": "Polygon",
        "coordinates": [
            [[80.754, 8.010], [80.762, 8.010], [80.762, 8.016], [80.754, 8.016], [80.754, 8.010]]
        ],
    }
    context = await enrich(spatial_world, event(area))
    assert context.geometry_kind == "area"
    assert {(z.name, z.relation) for z in context.inside_zones} == {
        ("Fixture Sanctuary", "intersects"),
        ("Fixture Drought Zone", "intersects"),
        ("Fixture Elephant Corridor", "intersects"),
    }


async def test_event_outside_every_zone(spatial_world: SpatialWorld) -> None:
    context = await enrich(spatial_world, event(point(80.72, 8.05)))
    assert context.inside_zones == []
    assert context.geofence_hits == []
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        hits = await session.scalar(
            text(
                "SELECT (SELECT count(*) FROM geo.event_zone_hit WHERE event_id = :id) "
                "+ (SELECT count(*) FROM geo.event_geofence_hit WHERE event_id = :id)"
            ),
            {"id": context.event_id},
        )
    assert hits == 0


@pytest.mark.parametrize(
    ("location", "inside"),
    [
        ((80.76, 8.05), True),  # on the outer edge of the park
        ((80.79, 8.07), True),  # on a corner of the park
        ((80.77, 8.055), True),  # on the edge of the enclave: the boundary belongs to the park
        ((80.775, 8.055), False),  # inside the enclave
        ((80.7599999, 8.05), False),  # just outside the outer edge
    ],
)
async def test_zone_boundaries_are_inclusive(
    spatial_world: SpatialWorld, location: tuple[float, float], inside: bool
) -> None:
    context = await enrich(spatial_world, event(point(*location)))
    assert ("Fixture National Park" in {z.name for z in context.inside_zones}) is inside


async def test_open_data_release_reports_its_missing_zone_layers(spatial_world: SpatialWorld) -> None:
    context = await engine(spatial_world).enrich(event(point(80.765, 8.045)))
    assert context.ref_data_release == OPEN_RELEASE
    assert context.inside_zones == []
    assert context.missing_layers == ["protected_area", "risk_zone"]


# --- geofences -------------------------------------------------------------------------------------------


async def test_event_inside_geofences(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    context = await enrich(spatial_world, event(point(80.749, 8.029)))
    hits = {hit.id: hit for hit in context.geofence_hits}
    assert set(hits) == {ops.polygon_fence, ops.circle_fence}
    assert [
        (hit.name, hit.kind, hit.tenant_id, hit.version, hit.relation) for hit in context.geofence_hits
    ] == [
        ("Fixture Circle Fence", "circle", TENANT_A.value, 1, "within"),
        ("Fixture Polygon Fence", "polygon", TENANT_A.value, 1, "within"),
    ]


async def test_polygon_geofence_edge_is_inside(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    on_edge = await enrich(spatial_world, event(point(80.748, 8.029)))
    outside = await enrich(spatial_world, event(point(80.7479999, 8.029)))
    assert ops.polygon_fence in {h.id for h in on_edge.geofence_hits}
    assert ops.polygon_fence not in {h.id for h in outside.geofence_hits}


# --- settlements, roads, devices -------------------------------------------------------------------------


async def test_event_near_a_settlement(spatial_world: SpatialWorld) -> None:
    context = await enrich(spatial_world, event(point(80.71, 8.0625)))
    assert context.nearest_settlement is not None
    assert (context.nearest_settlement.name, context.nearest_settlement.basis) == ("Fixture Village", "point")
    assert context.nearest_settlement.distance_m == pytest.approx(276.5, abs=1.0)


async def test_event_near_a_road(spatial_world: SpatialWorld) -> None:
    context = await enrich(spatial_world, event(point(80.73, ROAD_LATITUDE + 0.001)))
    assert context.nearest_road is not None
    assert (context.nearest_road.name, context.nearest_road.road_class, context.nearest_road.ref_code) == (
        "Fixture Road",
        "A",
        "A99",
    )
    assert context.nearest_road.distance_m == pytest.approx(110.6, abs=1.0)


async def test_nothing_within_the_search_radii(spatial_world: SpatialWorld) -> None:
    context = await enrich(
        spatial_world,
        event(point(80.60, 7.90)),
        settlement_radius_m=1_000,
        road_radius_m=1_000,
        device_radius_m=1_000,
    )
    assert (context.nearest_settlement, context.nearest_road, context.nearest_devices) == (None, None, [])


async def test_devices_report_whether_the_event_is_in_their_field_of_view(
    spatial_world: SpatialWorld,
) -> None:
    ops = spatial_world.ops
    ahead = await enrich(spatial_world, event(point(80.745, ROAD_LATITUDE + 0.002)))  # ~220 m north
    behind = await enrich(spatial_world, event(point(80.745, ROAD_LATITUDE - 0.002)))  # ~220 m south
    seen = {d.device_id: d.in_field_of_view for d in ahead.nearest_devices}
    unseen = {d.device_id: d.in_field_of_view for d in behind.nearest_devices}
    assert seen[ops.camera_a1] is True
    assert unseen[ops.camera_a1] is False
    assert seen[ops.sensor_a2] is None, "a device without a field of view"
    assert [d.distance_m for d in ahead.nearest_devices] == sorted(
        d.distance_m for d in ahead.nearest_devices
    )


async def test_the_reporting_device_is_not_its_own_neighbour(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    evt = event(None, sourceType="device", locationSource="device", deviceId=str(ops.camera_a1))
    context = await enrich(spatial_world, evt)
    assert ops.camera_a1 not in {d.device_id for d in context.nearest_devices}
    assert ops.sensor_a2 in {d.device_id for d in context.nearest_devices}


async def test_device_limit_zero_turns_the_device_lookup_off(spatial_world: SpatialWorld) -> None:
    context = await enrich(spatial_world, event(point(*CENTRE)), device_limit=0)
    assert context.nearest_devices == []
    assert context.search.device_limit == 0


# --- 499 / 500 / 501 m around a 500 m threshold ------------------------------------------------------------

LAYERS: Final = ("settlement", "road", "device", "circle_geofence")


@pytest.mark.parametrize("metres", [THRESHOLD_M - 1, THRESHOLD_M, THRESHOLD_M + 1])
@pytest.mark.parametrize("layer", LAYERS)
async def test_distance_threshold_of_500_m(
    spatial_world: SpatialWorld, thresholds: ThresholdWorld, layer: str, metres: float
) -> None:
    exact = thresholds.exact[layer, metres]
    assert metres - 1e-6 <= exact <= metres, "the probe position is at the intended distance"
    lon, lat = thresholds.positions[layer, metres]
    context = await engine(
        spatial_world,
        settlement_radius_m=THRESHOLD_M,
        road_radius_m=THRESHOLD_M,
        device_radius_m=THRESHOLD_M,
    ).enrich(event(point(lon, lat), tenant=TENANT_C), release_code=SYNTHETIC_RELEASE)
    expected = metres <= THRESHOLD_M
    if layer == "settlement":
        found = context.nearest_settlement
        assert (found is not None) is expected
        if found is not None:
            assert (found.name, found.distance_m) == ("Fixture Village", metres)
    elif layer == "road":
        road = context.nearest_road
        assert (road is not None) is expected
        if road is not None:
            assert (road.name, road.distance_m) == ("Fixture Road", metres)
    elif layer == "device":
        devices = {d.device_id: d.distance_m for d in context.nearest_devices}
        assert (thresholds.camera in devices) is expected
        if expected:
            assert devices[thresholds.camera] == metres
    else:
        assert (thresholds.fence in {h.id for h in context.geofence_hits}) is expected


async def test_threshold_equal_to_the_computed_distance_is_inclusive(
    spatial_world: SpatialWorld, thresholds: ThresholdWorld
) -> None:
    lon, lat = thresholds.positions["device", THRESHOLD_M + 1]
    exact = thresholds.exact["device", THRESHOLD_M + 1]
    evt = event(point(lon, lat), tenant=TENANT_C)
    at = await engine(spatial_world, device_radius_m=exact).enrich(evt, release_code=SYNTHETIC_RELEASE)
    below = await engine(spatial_world, device_radius_m=exact - 1e-6).enrich(
        evt, release_code=SYNTHETIC_RELEASE
    )
    assert thresholds.camera in {d.device_id for d in at.nearest_devices}
    assert thresholds.camera not in {d.device_id for d in below.nearest_devices}


# --- invalid coordinates ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "error", "member"),
    [
        (point(8.0305, 80.7505), CoordinateError, "likelySwapped"),
        (point(79.8612, 16.9271), CoordinateError, "serviceAreaBbox"),  # India, north of Sri Lanka
        (point(80.75, 91.0), CoordinateError, "position"),
        ({"type": "MultiPoint", "coordinates": [[80.75, 8.03], [8.03, 80.75]]}, CoordinateError, "path"),
        (
            {
                "type": "Polygon",
                "coordinates": [[[80.7, 8.0], [80.8, 8.1], [80.8, 8.0], [80.7, 8.1], [80.7, 8.0]]],
            },
            InvalidGeometryError,
            "reason",
        ),
        (
            {"type": "LineString", "coordinates": [[80.75, 8.03], [80.75, 8.03]]},
            InvalidGeometryError,
            "reason",
        ),
    ],
)
async def test_invalid_coordinates_are_rejected_and_nothing_is_stored(
    spatial_world: SpatialWorld, location: dict[str, Any], error: type[GisError], member: str
) -> None:
    evt = event(location)
    with pytest.raises(error) as info:
        await enrich(spatial_world, evt)
    assert member in info.value.extensions
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        stored = await session.scalar(
            text("SELECT count(*) FROM geo.event_location WHERE event_id = :id"), {"id": evt.event_id}
        )
    assert stored == 0


# --- tenant isolation ------------------------------------------------------------------------------------


async def test_each_tenant_sees_only_its_own_and_shared_objects(spatial_world: SpatialWorld) -> None:
    ops = spatial_world.ops
    location = point(80.7505, 8.0305)
    as_a = await enrich(spatial_world, event(location))
    as_b = await enrich(spatial_world, event(location, tenant=TENANT_B))
    as_authority = await enrich(spatial_world, event(location, tenant=AUTHORITY))
    fences = {
        name: {h.id for h in ctx.geofence_hits}
        for name, ctx in [("a", as_a), ("b", as_b), ("x", as_authority)]
    }
    devices = {
        name: {d.device_id for d in ctx.nearest_devices}
        for name, ctx in [("a", as_a), ("b", as_b), ("x", as_authority)]
    }
    assert fences["a"] == {ops.polygon_fence, ops.circle_fence}
    assert fences["b"] == {ops.b_private_fence, ops.b_authority_fence}
    assert fences["x"] == {ops.b_authority_fence}
    assert ops.camera_b1 not in devices["a"]
    assert {ops.camera_b1, ops.camera_b2_shared} <= devices["b"]
    assert not devices["b"] & {ops.camera_a1, ops.sensor_a2}
    assert devices["x"] == {ops.camera_b2_shared}, "an authority sees shared devices only"


async def test_the_same_event_id_is_separate_per_tenant(spatial_world: SpatialWorld) -> None:
    svc = engine(spatial_world)
    for_a = event(point(80.7505, 8.0305))
    for_b = for_a.model_copy(update={"tenant_id": TENANT_B.value})
    context_a = await svc.enrich(for_a, release_code=SYNTHETIC_RELEASE)
    context_b = await svc.enrich(for_b, release_code=SYNTHETIC_RELEASE)
    assert context_a.event_id == context_b.event_id
    assert context_a.geofence_hits != context_b.geofence_hits
    assert await svc.get(TENANT_A, for_a.event_id, for_a.observed_at) == context_a
    assert await svc.get(TENANT_B, for_b.event_id, for_b.observed_at) == context_b
    assert await svc.get(AUTHORITY, for_a.event_id, for_a.observed_at) is None


async def test_unregistered_tenants_cannot_store_events(spatial_world: SpatialWorld) -> None:
    with pytest.raises(UnknownTenantError) as info:
        await enrich(spatial_world, event(point(*CENTRE), tenant=TenantId("not-registered")))
    assert info.value.status_code == 403


# --- missing reference data ------------------------------------------------------------------------------


async def test_without_a_current_release_enrichment_is_unavailable(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        await session.execute(text("UPDATE meta.ref_data_release SET is_current = false WHERE is_current"))
    evt = event(point(*CENTRE))
    try:
        with pytest.raises(ReferenceDataUnavailableError) as info:
            await engine(spatial_world).enrich(evt)
    finally:
        async with transaction(spatial_world.migrator_sessions) as session:
            await session.execute(
                text("UPDATE meta.ref_data_release SET is_current = true WHERE code = :code"),
                {"code": OPEN_RELEASE},
            )
    assert info.value.status_code == 503
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        stored = await session.scalar(
            text("SELECT count(*) FROM geo.event_location WHERE event_id = :id"), {"id": evt.event_id}
        )
    assert stored == 0, "the location is not kept when no context can be computed"


async def test_unknown_release_is_not_found(spatial_world: SpatialWorld) -> None:
    with pytest.raises(ReleaseNotFoundError) as info:
        await engine(spatial_world).enrich(event(point(*CENTRE)), release_code="ref-2001.01")
    assert info.value.extensions == {"refDataRelease": "ref-2001.01"}


async def test_release_without_reference_data_yields_an_empty_context(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        release_id = (
            await session.execute(
                text(
                    "INSERT INTO meta.ref_data_release (code, description) "
                    "VALUES ('ref-2026.09-empty', 'published without data') RETURNING id"
                )
            )
        ).scalar_one()
        qa = await ReferenceQa(session).run(release_id)
        assert (qa.status, [f.check for f in qa.findings if f.severity != "info"]) == (
            "warnings",
            ["release.empty"],
        )
        await session.execute(
            text("UPDATE meta.ref_data_release SET status = 'published' WHERE code = 'ref-2026.09-empty'")
        )
    context = await engine(spatial_world).enrich(event(point(*CENTRE)), release_code="ref-2026.09-empty")
    assert context.ref_data_release == "ref-2026.09-empty"
    assert context.missing_layers == ["admin_area", "settlement", "road", "protected_area", "risk_zone"]
    assert (context.admin.province, context.nearest_settlement, context.nearest_road) == (None, None, None)
    assert context.inside_zones == []
    # Operational data does not depend on the release.
    assert context.geofence_hits != []


async def test_partial_admin_coverage_leaves_lower_levels_empty(spatial_world: SpatialWorld) -> None:
    # Kandy: the open data has provinces and districts everywhere, DS and GN divisions only near Habarana.
    context = await engine(spatial_world).enrich(event(point(80.635, 7.2906)))
    admin = context.admin
    assert admin.province is not None
    assert admin.district is not None
    assert (admin.province.name, admin.district.name) == ("Central Province", "Kandy District")
    assert (admin.ds_division, admin.gn_division) == (None, None)
    assert admin.codes.l3 is None
    assert context.missing_layers == ["protected_area", "risk_zone"]


# --- concurrency ---------------------------------------------------------------------------------------


async def test_the_same_event_delivered_twice_at_once_is_stored_once(spatial_world: SpatialWorld) -> None:
    """At-least-once delivery: two enrichments of one event may overlap."""
    evt = event(point(*MULTI_ZONE_POINT))
    svc = engine(spatial_world)
    first, second = await asyncio.gather(
        svc.enrich(evt, release_code=SYNTHETIC_RELEASE), svc.enrich(evt, release_code=SYNTHETIC_RELEASE)
    )
    assert len(first.inside_zones) == len(second.inside_zones) == 3
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        counts = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM geo.event_location WHERE event_id = :id) AS locations, "
                    "(SELECT count(*) FROM geo.event_geo_context WHERE event_id = :id) AS contexts, "
                    "(SELECT count(*) FROM geo.event_zone_hit WHERE event_id = :id) AS zones"
                ),
                {"id": evt.event_id},
            )
        ).one()
    assert tuple(counts) == (1, 1, 3)
    stored = await svc.get(TENANT_A, evt.event_id, evt.observed_at)
    assert stored in (first, second)


async def test_moving_an_event_removes_the_hits_it_no_longer_has(spatial_world: SpatialWorld) -> None:
    svc = engine(spatial_world)
    evt = event(point(*MULTI_ZONE_POINT))
    await svc.enrich(evt, release_code=SYNTHETIC_RELEASE)
    moved = evt.model_copy(update={"location": event(point(80.785, 8.065)).location})
    context = await svc.enrich(moved, release_code=SYNTHETIC_RELEASE)
    assert [zone.name for zone in context.inside_zones] == ["Fixture National Park"]
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        rows = (
            (
                await session.execute(
                    text("SELECT zone_id FROM geo.event_zone_hit WHERE event_id = :id"), {"id": evt.event_id}
                )
            )
            .scalars()
            .all()
        )
    assert rows == [context.inside_zones[0].id]


# --- round trips -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("location", "device", "statements"),
    [
        (point(80.72, 8.05), False, 4),  # nothing nearby: tenant, location, lookup, context
        (point(*MULTI_ZONE_POINT), False, 4),  # three zones, geofences and devices: still four
        (None, True, 5),  # device event: plus the device and field-of-view lookup
    ],
)
async def test_database_statements_do_not_grow_with_the_number_of_hits(
    spatial_world: SpatialWorld, location: dict[str, Any] | None, device: bool, statements: int
) -> None:
    fields: dict[str, Any] = {}
    if device:
        fields = {
            "sourceType": "device",
            "locationSource": "device",
            "deviceId": str(spatial_world.ops.camera_a1),
        }
    evt = event(location, **fields)
    executed: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        executed.append(statement)

    sync_engine = spatial_world.app_engine.sync_engine
    sa_event.listen(sync_engine, "before_cursor_execute", count)
    try:
        context = await enrich(spatial_world, evt)
    finally:
        sa_event.remove(sync_engine, "before_cursor_execute", count)
    assert len(executed) == statements, executed
    if location is not None and location["coordinates"] == list(MULTI_ZONE_POINT):
        assert len(context.inside_zones) == 3
