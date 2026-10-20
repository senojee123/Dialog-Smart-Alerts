"""``GET /geo/v1/events``: reading back what enrichment stored, by time, area and attribute.

The events are created through the enrichment engine, so what the query returns is the real stored
geometry and the real stored geo-context - including the geofence hits and administrative areas the
filters use.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from app.schemas.events import EventLocationIn
from app.services.enrichment import GeoContextLimits, GeoContextService
from tests.integration.api_client import Api, api_client_for, assert_problem, ok
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import CENTRE, SYNTHETIC_RELEASE, TENANT_A, TENANT_B

EVENTS: Final = "/geo/v1/events"
MULTI_ZONE_POINT: Final = (80.758, 8.015)
VILLAGE: Final = (80.71, 8.06)
CAMERA_POSITION: Final = (80.7450, 8.0100)
WINDOW: Final = {"from": "2026-09-10T00:00:00Z", "to": "2026-09-11T00:00:00Z"}


def _at(hour: int) -> datetime:
    return datetime(2026, 9, 10, hour, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Events:
    """The events these tests query, newest last."""

    corridor: str
    centre: str
    village: str
    from_camera: str
    other_tenant: str


def point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


def _event(event_id: str, tenant: str, observed: datetime, **fields: Any) -> EventLocationIn:
    data: dict[str, Any] = {
        "eventId": event_id,
        "tenantId": tenant,
        "observedAt": observed.isoformat(),
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
    }
    data.update(fields)
    return EventLocationIn.model_validate(data)


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    async with api_client_for(spatial_world) as client:
        yield client


@pytest.fixture(scope="module")
async def events(spatial_world: SpatialWorld) -> Events:
    service = GeoContextService(spatial_world.app_sessions, spatial_world.service_area, GeoContextLimits())
    seeded = Events(
        corridor="evt-corridor",
        centre="evt-centre",
        village="evt-village",
        from_camera="evt-camera",
        other_tenant="evt-other-tenant",
    )
    await service.enrich(
        _event(seeded.corridor, TENANT_A.value, _at(4), location=point(*MULTI_ZONE_POINT)),
        release_code=SYNTHETIC_RELEASE,
    )
    await service.enrich(
        _event(seeded.centre, TENANT_A.value, _at(5), location=point(*CENTRE)),
        release_code=SYNTHETIC_RELEASE,
    )
    await service.enrich(
        _event(
            seeded.village,
            TENANT_A.value,
            _at(6),
            location=point(*VILLAGE),
            eventType="infrastructure.sensor_offline",
        ),
        release_code=SYNTHETIC_RELEASE,
    )
    await service.enrich(
        _event(
            seeded.from_camera,
            TENANT_A.value,
            _at(7),
            sourceType="device",
            locationSource="device",
            deviceId=str(spatial_world.ops.camera_a1),
        ),
        release_code=SYNTHETIC_RELEASE,
    )
    await service.enrich(
        _event(seeded.other_tenant, TENANT_B.value, _at(5), location=point(*CENTRE)),
        release_code=SYNTHETIC_RELEASE,
    )
    return seeded


def ids(collection: dict[str, Any]) -> list[str]:
    return [feature["id"] for feature in collection["features"]]


# --- the window ------------------------------------------------------------------------------------------


async def test_events_come_back_newest_first_inside_the_window(api: Api, events: Events) -> None:
    body = ok(await api.get(EVENTS, tenant=TENANT_A, params=WINDOW))

    assert ids(body) == [events.from_camera, events.village, events.centre, events.corridor]
    assert body["type"] == "FeatureCollection"
    assert body["window"] == {"from": "2026-09-10T00:00:00Z", "to": "2026-09-11T00:00:00Z"}
    assert body["layer"] == "geo.event_location"


async def test_the_window_bounds_what_is_returned(api: Api, events: Events) -> None:
    body = ok(
        await api.get(
            EVENTS,
            tenant=TENANT_A,
            params={"from": "2026-09-10T05:30:00Z", "to": "2026-09-10T06:30:00Z"},
        )
    )

    assert ids(body) == [events.village]


async def test_the_window_defaults_to_the_last_day(api: Api, events: Events) -> None:
    body = ok(await api.get(EVENTS, tenant=TENANT_A))

    assert body["features"] == []  # the fixture events were observed long before now
    window = body["window"]
    assert window["from"] < window["to"]


async def test_a_window_longer_than_a_month_is_refused(api: Api) -> None:
    response = await api.get(
        EVENTS, tenant=TENANT_A, params={"from": "2026-01-01T00:00:00Z", "to": "2026-09-11T00:00:00Z"}
    )

    problem = assert_problem(response, 422, "time_window_too_large")
    assert problem["maxWindowDays"] == 31


async def test_a_window_that_ends_before_it_starts_is_refused(api: Api) -> None:
    response = await api.get(
        EVENTS, tenant=TENANT_A, params={"from": "2026-09-11T00:00:00Z", "to": "2026-09-10T00:00:00Z"}
    )

    assert_problem(response, 422, "validation_error")


# --- viewport and attributes -----------------------------------------------------------------------------


async def test_a_viewport_selects_the_events_inside_it(api: Api, events: Events) -> None:
    body = ok(await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "bbox": "80.700,8.050,80.720,8.070"}))

    assert ids(body) == [events.village]


async def test_events_can_be_filtered_by_type(api: Api, events: Events) -> None:
    body = ok(
        await api.get(
            EVENTS,
            tenant=TENANT_A,
            params={**WINDOW, "eventType": "infrastructure.sensor_offline"},
        )
    )

    assert ids(body) == [events.village]


async def test_events_can_be_filtered_by_the_device_that_reported_them(api: Api, events: Events) -> None:
    body = ok(
        await api.get(
            EVENTS,
            tenant=TENANT_A,
            params={**WINDOW, "deviceId": str(api.world.ops.camera_a1)},
        )
    )

    assert ids(body) == [events.from_camera]
    assert body["features"][0]["geometry"]["coordinates"] == list(CAMERA_POSITION)


async def test_events_can_be_filtered_by_source_type(api: Api, events: Events) -> None:
    body = ok(await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "sourceType": "device"}))

    assert ids(body) == [events.from_camera]


async def test_an_unknown_source_type_is_refused(api: Api) -> None:
    response = await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "sourceType": "carrier-pigeon"})

    assert_problem(response, 422, "unsupported_filter")


# --- geofence and administrative filtering ---------------------------------------------------------------


async def test_events_can_be_filtered_by_the_geofence_they_were_found_in(api: Api, events: Events) -> None:
    body = ok(
        await api.get(
            EVENTS,
            tenant=TENANT_A,
            params={**WINDOW, "geofenceId": str(api.world.ops.circle_fence)},
        )
    )

    assert ids(body) == [events.centre]


async def test_a_geofence_of_another_tenant_matches_nothing(api: Api, events: Events) -> None:
    body = ok(
        await api.get(
            EVENTS,
            tenant=TENANT_A,
            params={**WINDOW, "geofenceId": str(api.world.ops.b_private_fence)},
        )
    )

    assert body["features"] == []


async def test_events_can_be_filtered_by_administrative_area(api: Api, events: Events) -> None:
    east = ok(await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "adminAreaCode": "SYN-D2"}))
    west = ok(await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "adminAreaCode": "SYN-D1"}))

    assert ids(east) == [events.corridor]
    assert events.village in ids(west)
    assert events.corridor not in ids(west)


async def test_events_can_be_filtered_by_administrative_area_id(api: Api, events: Events) -> None:
    from_context = ok(await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "adminAreaCode": "SYN-D2"}))
    feature = from_context["features"][0]
    assert feature["properties"]["admin"]["l2"] == "SYN-D2"

    detail = ok(
        await api.get(
            "/geo/v1/layers/ref.admin_area/features",
            params={"refDataRelease": SYNTHETIC_RELEASE, "code": "SYN-D2", "includeGeometry": False},
        )
    )
    area_id = detail["features"][0]["id"]

    body = ok(await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "adminAreaId": area_id}))

    assert ids(body) == [events.corridor]
    assert uuid.UUID(area_id)


async def test_every_event_carries_the_context_that_was_computed_for_it(api: Api, events: Events) -> None:
    body = ok(await api.get(EVENTS, tenant=TENANT_A, params=WINDOW))

    corridor = next(f for f in body["features"] if f["id"] == events.corridor)
    assert corridor["properties"]["admin"] == {"l1": "SYN-P1", "l2": "SYN-D2", "l3": "SYN-S3", "l4": None}
    assert corridor["properties"]["refDataRelease"] == SYNTHETIC_RELEASE
    assert corridor["properties"]["geometryKind"] == "point"
    assert corridor["properties"]["eventType"] == "wildlife.elephant_detected"
    assert corridor["properties"]["tenantId"] == TENANT_A.value


# --- paging ----------------------------------------------------------------------------------------------


async def test_events_are_paged_newest_first(api: Api, events: Events) -> None:
    params = {**WINDOW, "limit": 2}

    first = ok(await api.get(EVENTS, tenant=TENANT_A, params=params))
    second = ok(await api.get(EVENTS, tenant=TENANT_A, params={**params, "cursor": first["nextCursor"]}))

    assert ids(first) == [events.from_camera, events.village]
    assert ids(second) == [events.centre, events.corridor]
    assert second["nextCursor"] is None


async def test_paging_stays_in_the_window_the_first_page_used(api: Api, events: Events) -> None:
    """With an open-ended window ('to' defaults to now), the pages must still be one result set."""
    params = {"from": "2026-09-10T00:00:00Z", "limit": 2}

    first = ok(await api.get(EVENTS, tenant=TENANT_A, params=params))
    second = ok(await api.get(EVENTS, tenant=TENANT_A, params={**params, "cursor": first["nextCursor"]}))

    assert ids(first) == [events.from_camera, events.village]
    assert ids(second) == [events.centre, events.corridor]
    assert second["window"] == first["window"]


async def test_a_cursor_cannot_widen_the_window(api: Api, events: Events) -> None:
    """The cursor is not a capability: the window it carries is checked like any other input."""
    first = ok(await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "limit": 2}))
    payload = json.loads(base64.urlsafe_b64decode(first["nextCursor"] + "=="))
    payload["v"]["wf"] = "2020-01-01T00:00:00+00:00"
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

    response = await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "limit": 2, "cursor": forged})

    assert_problem(response, 422, "time_window_too_large")


async def test_a_cursor_belongs_to_the_window_it_was_made_for(api: Api, events: Events) -> None:
    first = ok(await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "limit": 2}))

    response = await api.get(
        EVENTS,
        tenant=TENANT_A,
        params={
            "from": "2026-09-10T02:00:00Z",
            "to": "2026-09-11T00:00:00Z",
            "limit": 2,
            "cursor": first["nextCursor"],
        },
    )

    assert_problem(response, 422, "invalid_cursor")


# --- tenant isolation ------------------------------------------------------------------------------------


async def test_a_tenant_sees_only_its_own_events(api: Api, events: Events) -> None:
    for_a = ok(await api.get(EVENTS, tenant=TENANT_A, params=WINDOW))
    for_b = ok(await api.get(EVENTS, tenant=TENANT_B, params=WINDOW))

    assert events.other_tenant not in ids(for_a)
    assert ids(for_b) == [events.other_tenant]
    assert {f["properties"]["tenantId"] for f in for_b["features"]} == {TENANT_B.value}


async def test_an_event_query_cannot_name_another_tenant(api: Api) -> None:
    response = await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "tenantId": TENANT_B.value})

    assert_problem(response, 403, "forbidden")


async def test_a_tenant_the_request_does_not_act_for_is_refused(api: Api) -> None:
    response = await api.get(EVENTS, tenant=TENANT_A, params={**WINDOW, "tenantId": TENANT_B.value})

    assert_problem(response, 403, "forbidden")
