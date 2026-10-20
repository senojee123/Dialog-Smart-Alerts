"""The MVP scenario end to end, over HTTP, against the real application, PostGIS and row-level security.

One tenant maintains a geofence, a spatial event is submitted, its location is validated, the geo-context
is computed (administrative areas, nearest settlement and road, zones, geofence hits), stored and
returned; the event is then found the way the map finds it (events by viewport) and by spatial queries,
and the geofence is managed (replaced, which changes the hits, and archived). The map rendering itself is
checked in a browser by ``frontend/e2e/map.e2e.ts``.

Positions are in the synthetic fixture world (``data/fixtures/synthetic_habarana``), whose answers are
known exactly; ``MULTI_ZONE_POINT`` lies in a sanctuary and two overlapping risk zones.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import text

from app.core.tenancy import TenantId
from app.db.session import transaction
from tests.integration.api_client import Api, api_client_for, assert_problem, ok
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import SYNTHETIC_RELEASE, point

TENANT: Final = TenantId("e2e-tenant")
MULTI_ZONE_POINT: Final = (80.758, 8.015)
RELEASE: Final = {"refDataRelease": SYNTHETIC_RELEASE}


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    async with transaction(spatial_world.migrator_sessions) as session:
        await session.execute(
            text("INSERT INTO meta.tenant (tenant_id, name) VALUES (:t, 'End-to-end tenant')"),
            {"t": TENANT.value},
        )
    async with api_client_for(spatial_world) as client:
        yield client


def event(event_id: str, location: dict[str, Any], observed: datetime) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "tenantId": TENANT.value,
        "observedAt": observed.isoformat(),
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": location,
        "locationAccuracyM": 20,
    }


async def test_an_event_from_submission_to_map_queries_and_geofence_management(
    api: Api, spatial_world: SpatialWorld
) -> None:
    call: dict[str, Any] = {"tenant": TENANT}
    lon, lat = MULTI_ZONE_POINT
    observed = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0)

    # 12a. Geofence management: the tenant creates a circle around the place the event will be.
    created = await api.post(
        "/geo/v1/geofences",
        json={
            "name": "E2E watch zone",
            "definition": {"kind": "circle", "geometry": point(lon, lat), "radiusM": 300},
            "status": "active",
            "effectiveDuring": {"from": (observed - timedelta(days=1)).isoformat()},
        },
        params={"tenantId": TENANT.value},
        **call,
    )
    fence = ok(created, 201)
    assert created.headers["location"].endswith(f"/geo/v1/geofences/{fence['id']}")
    assert (fence["version"], fence["tenantId"], fence["status"]) == (1, TENANT.value, "active")

    # 1-2. A spatial event is submitted, and its location validated: swapped axes are refused, and
    # nothing is stored.
    swapped = await api.post(
        "/geo/v1/enrich", json=event("e2e-evt-swapped", point(lat, lon), observed), params=RELEASE, **call
    )
    assert assert_problem(swapped, 422, "invalid_coordinate")["likelySwapped"] is True
    bowtie = {
        "type": "Polygon",
        "coordinates": [[[80.70, 8.00], [80.80, 8.10], [80.80, 8.00], [80.70, 8.10], [80.70, 8.00]]],
    }
    invalid = await api.post(
        "/geo/v1/enrich", json=event("e2e-evt-bowtie", bowtie, observed), params=RELEASE, **call
    )
    assert_problem(invalid, 422, "invalid_geometry")

    # 3-9. The valid event is enriched, stored and returned.
    response = await api.post(
        "/geo/v1/enrich", json=event("e2e-evt-1", point(lon, lat), observed), params=RELEASE, **call
    )
    context = ok(response)
    assert (context["schema"], context["eventId"], context["tenantId"]) == (
        "geo-context/1",
        "e2e-evt-1",
        TENANT.value,
    )
    assert context["refDataRelease"] == SYNTHETIC_RELEASE
    # 4. Administrative context: the whole hierarchy the fixture world has at this point.
    assert context["admin"]["codes"] == {"l1": "SYN-P1", "l2": "SYN-D2", "l3": "SYN-S3", "l4": None}
    assert context["admin"]["province"]["name"] == "Fixture Province"
    # 5-6. Nearest settlement and road, with their distances in metres (EPSG:5235).
    assert context["nearestSettlement"]["name"] == "Fixture Town"
    assert context["nearestSettlement"]["distanceM"] >= 0
    assert context["nearestRoad"]["name"] == "Fixture Road"
    assert 0 < context["nearestRoad"]["distanceM"] < 1_000
    # 7. Zone intersections: a sanctuary and two overlapping risk zones.
    assert [(zone["type"], zone["name"], zone["relation"]) for zone in context["insideZones"]] == [
        ("protected_area", "Fixture Sanctuary", "within"),
        ("risk_zone", "Fixture Drought Zone", "within"),
        ("risk_zone", "Fixture Elephant Corridor", "within"),
    ]
    # 8. Geofence hits: the circle just created, at the version it was tested against.
    hits = {hit["id"]: hit for hit in context["geofenceHits"]}
    assert hits[fence["id"]]["version"] == 1
    assert hits[fence["id"]]["relation"] == "within"
    # 9. Persisted: the stored document is the one returned.
    async with transaction(spatial_world.app_sessions, TENANT) as session:
        stored = await session.scalar(
            text("SELECT document FROM geo.event_geo_context WHERE event_id = 'e2e-evt-1'")
        )
        rejected = await session.scalar(
            text("SELECT count(*) FROM geo.event_location WHERE event_id LIKE 'e2e-evt-%'")
        )
    assert stored == context
    assert rejected == 1  # the swapped and invalid submissions left nothing behind

    # 10. The map finds it: the event layer asks for events in the viewport and time window.
    window = {
        "from": (observed - timedelta(hours=1)).isoformat(),
        "to": (observed + timedelta(hours=1)).isoformat(),
        "tenantId": TENANT.value,
    }
    viewport = {**window, "bbox": f"{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}"}
    events = ok(await api.get("/geo/v1/events", params=viewport, **call))
    assert [feature["id"] for feature in events["features"]] == ["e2e-evt-1"]
    properties = events["features"][0]["properties"]
    assert properties["admin"] == {"l1": "SYN-P1", "l2": "SYN-D2", "l3": "SYN-S3", "l4": None}
    assert events["features"][0]["geometry"] == point(lon, lat)
    elsewhere = {**window, "bbox": "80.60,7.90,80.65,7.95"}
    assert ok(await api.get("/geo/v1/events", params=elsewhere, **call))["features"] == []
    # ... and the geofence layer draws the circle.
    fences = ok(
        await api.get(
            "/geo/v1/layers/ops.geofence/features",
            params={"bbox": viewport["bbox"], "tenantId": TENANT.value},
            **call,
        )
    )
    assert fence["id"] in {feature["id"] for feature in fences["features"]}

    # 11. Spatial queries retrieve it. Events are time-partitioned, so they are queried within a window:
    # by area (above), by the geofence they hit and by the administrative area they fell in.
    by_fence = ok(await api.get("/geo/v1/events", params={**window, "geofenceId": fence["id"]}, **call))
    assert [feature["id"] for feature in by_fence["features"]] == ["e2e-evt-1"]
    by_area = ok(await api.get("/geo/v1/events", params={**window, "adminAreaCode": "SYN-S3"}, **call))
    assert [feature["id"] for feature in by_area["features"]] == ["e2e-evt-1"]
    containing = ok(
        await api.post(
            "/geo/v1/query/contains",
            json={"target": "ops.geofence", "geometry": point(lon, lat)},
            params={"tenantId": TENANT.value},
            **call,
        )
    )
    assert fence["id"] in {feature["id"] for feature in containing["features"]}
    # The same position, asked of the other layers: what is near it, and within what distance.
    near = ok(
        await api.post(
            "/geo/v1/query/within-distance",
            json={"target": "ops.geofence", "geometry": point(lon + 0.004, lat), "distanceM": 500},
            params={"tenantId": TENANT.value},
            **call,
        )
    )
    assert [feature["id"] for feature in near["features"]] == [fence["id"]]
    assert 100 < near["features"][0]["properties"]["distanceM"] < 200  # 440 m to the centre, radius 300 m
    nearest = ok(
        await api.post(
            "/geo/v1/query/nearest",
            json={
                "target": "ref.settlement",
                "geometry": point(lon, lat),
                "limit": 1,
                "refDataRelease": SYNTHETIC_RELEASE,
            },
            **call,
        )
    )
    assert [feature["properties"]["name"] for feature in nearest["features"]] == [
        context["nearestSettlement"]["name"]
    ]

    # 12b. Geofence management: moving the circle away changes what a new event hits.
    replaced = ok(
        await api.put(
            f"/geo/v1/geofences/{fence['id']}",
            json={
                "name": "E2E watch zone (moved)",
                "definition": {"kind": "circle", "geometry": point(lon + 0.05, lat), "radiusM": 300},
                "status": "active",
                "effectiveDuring": {"from": (observed - timedelta(days=1)).isoformat()},
                "version": 1,
            },
            params={"tenantId": TENANT.value},
            **call,
        )
    )
    assert replaced["version"] == 2
    stale = await api.put(
        f"/geo/v1/geofences/{fence['id']}",
        json={
            "name": "E2E watch zone (stale)",
            "definition": {"kind": "circle", "geometry": point(lon, lat), "radiusM": 300},
            "status": "active",
            "version": 1,
        },
        params={"tenantId": TENANT.value},
        **call,
    )
    assert assert_problem(stale, 409, "version_conflict")["currentVersion"] == 2
    second = ok(
        await api.post(
            "/geo/v1/enrich", json=event("e2e-evt-2", point(lon, lat), observed), params=RELEASE, **call
        )
    )
    assert fence["id"] not in {hit["id"] for hit in second["geofenceHits"]}
    # The first event keeps the hit it had: stored contexts are facts about the moment they were made.
    by_fence = ok(await api.get("/geo/v1/events", params={**window, "geofenceId": fence["id"]}, **call))
    assert [feature["id"] for feature in by_fence["features"]] == ["e2e-evt-1"]

    # 12c. Archiving retires it; it is still readable, but no longer active.
    archived = await api.delete(
        f"/geo/v1/geofences/{fence['id']}", params={"tenantId": TENANT.value, "version": 2}, **call
    )
    assert archived.status_code in (200, 204), archived.text
    read = ok(await api.get(f"/geo/v1/geofences/{fence['id']}", params={"tenantId": TENANT.value}, **call))
    assert read["status"] == "archived"

    # Another tenant sees none of it.
    other: dict[str, Any] = {"tenant": TenantId("fixture-tenant-b")}
    theirs = ok(await api.get("/geo/v1/events", params={**window, "tenantId": "fixture-tenant-b"}, **other))
    assert "e2e-evt-1" not in {feature["id"] for feature in theirs["features"]}
    hidden = await api.get(
        f"/geo/v1/geofences/{fence['id']}", params={"tenantId": "fixture-tenant-b"}, **other
    )
    assert_problem(hidden, 404, "geofence_not_found")
