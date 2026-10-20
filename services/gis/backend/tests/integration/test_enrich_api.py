"""``POST /geo/v1/enrich`` end to end: HTTP, the tenant a request acts for, PostGIS and row-level security.

The OpenAPI response example is checked against a real result here. After an intended change, regenerate
it with ``GIS_UPDATE_EXAMPLES=1 pytest tests/integration/test_enrich_api.py`` and review the diff.
"""

from __future__ import annotations

import os
import pprint
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy import text

from app.api.v1 import enrichment_examples
from app.api.v1.enrichment_examples import REQUEST_EXAMPLES, RESPONSE_EXAMPLE
from app.core.caller import TENANT_HEADER
from app.core.tenancy import TenantId
from app.db.session import transaction
from app.main import create_app
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import (
    CENTRE,
    OPEN_RELEASE,
    SYNTHETIC_RELEASE,
    TENANT_A,
    TENANT_B,
    point,
)

ENRICH: Final = "/geo/v1/enrich"
EXAMPLE_TENANT: Final = TenantId("wildlife-dept")
PROBLEM: Final = "urn:gis-core-service:problem:"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ids = iter(range(1, 1_000_000))


@dataclass(frozen=True, slots=True)
class Api:
    client: httpx.AsyncClient
    world: SpatialWorld
    example_camera: uuid.UUID
    example_fence: uuid.UUID

    async def enrich(
        self, body: dict[str, Any], tenant: TenantId | None = None, params: dict[str, str] | None = None
    ) -> httpx.Response:
        """Enrich ``body`` acting for ``tenant`` (default: the event's own tenant)."""
        acting = tenant or TenantId(str(body["tenantId"]))
        return await self.client.post(ENRICH, json=body, headers={TENANT_HEADER: acting.value}, params=params)


def body(location: dict[str, Any] | None, tenant: TenantId = TENANT_A, **fields: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "eventId": f"evt-api-{next(_ids)}",
        "tenantId": tenant.value,
        "observedAt": "2026-09-10T10:00:00+05:30",
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": location,
    }
    data.update(fields)
    return data


async def _example_operational_data(world: SpatialWorld) -> tuple[uuid.UUID, uuid.UUID]:
    """A camera and a watch zone of the example tenant near Habarana junction."""
    async with transaction(world.migrator_sessions) as session:
        await session.execute(
            text(
                "INSERT INTO meta.tenant (tenant_id, name, kind) "
                "VALUES (:t, 'Wildlife Department', 'organisation')"
            ),
            {"t": EXAMPLE_TENANT.value},
        )
    async with transaction(world.app_sessions, EXAMPLE_TENANT) as session:
        camera = await session.scalar(
            text(
                "INSERT INTO ops.device (name, external_id, device_type, geom, position_source, "
                "position_accuracy_m) VALUES ('HB-CAM-01', 'HB-CAM-01', 'camera', "
                "public.ST_GeomFromText('POINT(80.752 8.040)', 4326), 'gps', 5) RETURNING id"
            )
        )
        await session.execute(
            text(
                "INSERT INTO ops.device_field_of_view (device_id, geometry_method, bearing_deg, fov_deg, "
                "range_m, valid_during) VALUES (:id, 'modelled', 225, 70, 600, tstzrange('2026-01-01', NULL))"
            ),
            {"id": camera},
        )
        fence = await session.scalar(
            text(
                "INSERT INTO ops.geofence (name, geofence_kind, definition_geom, radius_m, status, "
                "effective_during) VALUES ('Habarana junction watch zone', 'circle', "
                "public.ST_GeomFromText('POINT(80.7487 8.0356)', 4326), 750, 'active', "
                "tstzrange('2026-01-01', NULL)) RETURNING id"
            )
        )
    return uuid.UUID(str(camera)), uuid.UUID(str(fence))


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    camera, fence = await _example_operational_data(spatial_world)
    settings = spatial_world.settings.model_copy(
        update={"tenant_id": TENANT_A.value, "enrichment_settlement_radius_m": 60_000.0}
    )
    app = create_app(settings)
    async with (
        LifespanManager(app) as manager,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=manager.app), base_url="http://test") as client,
    ):
        yield Api(client, spatial_world, camera, fence)


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    problem: dict[str, Any] = response.json()
    assert problem["type"] == f"{PROBLEM}{code}", problem
    assert problem["status"] == status
    assert problem["requestId"] == response.headers["x-request-id"]
    return problem


async def stored_locations(world: SpatialWorld, tenant: TenantId, event_id: str) -> int:
    async with transaction(world.app_sessions, tenant) as session:
        count = await session.scalar(
            text("SELECT count(*) FROM geo.event_location WHERE event_id = :id"), {"id": event_id}
        )
    return int(count or 0)


# --- success ---------------------------------------------------------------------------------------------


async def test_enrich_returns_and_stores_the_geo_context(api: Api) -> None:
    ops = api.world.ops
    request = body(point(80.7505, 8.0305), metadata={"confidence": 0.93})
    response = await api.enrich(request, params={"refDataRelease": SYNTHETIC_RELEASE})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    context = response.json()
    assert list(context) == [
        "schema",
        "eventId",
        "tenantId",
        "observedAt",
        "locationSource",
        "geometryKind",
        "admin",
        "nearestSettlement",
        "nearestRoad",
        "insideZones",
        "geofenceHits",
        "nearestDevices",
        "missingLayers",
        "search",
        "refDataRelease",
        "computedAt",
    ]
    assert context["schema"] == "geo-context/1"
    assert (context["eventId"], context["tenantId"]) == (request["eventId"], TENANT_A.value)
    assert context["observedAt"] == "2026-09-10T04:30:00Z"
    assert context["refDataRelease"] == SYNTHETIC_RELEASE
    assert context["admin"]["codes"] == {"l1": "SYN-P1", "l2": "SYN-D2", "l3": "SYN-S3", "l4": None}
    assert context["nearestSettlement"]["name"] == "Fixture Town"
    assert context["nearestSettlement"]["distanceM"] == 0
    assert {hit["id"] for hit in context["geofenceHits"]} == {str(ops.polygon_fence), str(ops.circle_fence)}
    assert context["search"]["settlementRadiusM"] == 60_000
    async with transaction(api.world.app_sessions, TENANT_A) as session:
        document = await session.scalar(
            text("SELECT document FROM geo.event_geo_context WHERE event_id = :id"),
            {"id": request["eventId"]},
        )
    assert document == context


async def test_resending_an_event_replaces_it(api: Api) -> None:
    request = body(point(*CENTRE))
    first = await api.enrich(request, params={"refDataRelease": SYNTHETIC_RELEASE})
    moved = {**request, "location": point(80.785, 8.065)}
    second = await api.enrich(moved, params={"refDataRelease": SYNTHETIC_RELEASE})
    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["geofenceHits"] != []
    assert second.json()["geofenceHits"] == []
    assert [zone["name"] for zone in second.json()["insideZones"]] == ["Fixture National Park"]
    assert await stored_locations(api.world, TENANT_A, request["eventId"]) == 1


async def test_device_event_without_location_uses_the_device_position(api: Api) -> None:
    request = body(
        None,
        tenant=EXAMPLE_TENANT,
        sourceType="device",
        locationSource="device",
        deviceId=str(api.example_camera),
        observedAt="2026-09-14T08:35:00+05:30",
    )
    response = await api.enrich(request)
    assert response.status_code == 200, response.text
    context = response.json()
    assert context["locationSource"] == "device"
    assert context["refDataRelease"] == OPEN_RELEASE
    assert context["admin"]["gnDivision"]["name"] == "Habarana"
    assert [hit["id"] for hit in context["geofenceHits"]] == [str(api.example_fence)]
    assert str(api.example_camera) not in {device["deviceId"] for device in context["nearestDevices"]}


async def test_openapi_response_example_is_a_real_result(api: Api) -> None:
    example = REQUEST_EXAMPLES["point"]["value"]
    response = await api.enrich(dict(example))
    assert response.status_code == 200, response.text
    actual = response.json()
    if os.environ.get("GIS_UPDATE_EXAMPLES") == "1":
        _write_response_example(actual)
    assert _masked(actual) == _masked(RESPONSE_EXAMPLE), (
        "the OpenAPI example is stale; regenerate with GIS_UPDATE_EXAMPLES=1"
    )
    assert actual["geofenceHits"][0]["id"] == str(api.example_fence)
    assert actual["nearestDevices"][0]["inFieldOfView"] is True


def _masked(value: Any, key: str | None = None) -> Any:
    """Row ids differ per database and computedAt per run; everything else must match."""
    if isinstance(value, dict):
        return {k: _masked(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_masked(item) for item in value]
    if key == "computedAt" or (isinstance(value, str) and _UUID.fullmatch(value)):
        return "<varies>"
    return value


def _write_response_example(actual: dict[str, Any]) -> None:
    path = Path(enrichment_examples.__file__)
    source = path.read_text(encoding="utf-8")
    marker = "RESPONSE_EXAMPLE: Final[dict[str, Any]] = "
    head = source[: source.index(marker)]
    path.write_text(
        f"{head}{marker}{pprint.pformat(actual, width=100, sort_dicts=False)}\n", encoding="utf-8"
    )


# --- the tenant a request acts for -----------------------------------------------------------------------


async def test_an_event_of_another_tenant_is_refused(api: Api) -> None:
    request = body(point(*CENTRE), tenant=TENANT_B)
    response = await api.enrich(request, TENANT_A)
    problem = assert_problem(response, 403, "forbidden")
    assert problem["tenantId"] == TENANT_B.value
    assert await stored_locations(api.world, TENANT_B, request["eventId"]) == 0


async def test_without_a_tenant_header_the_platforms_organisation_is_used(api: Api) -> None:
    """No credentials are asked for: the request acts for GIS_TENANT_ID (here tenant A)."""
    request = body(point(*CENTRE))
    response = await api.client.post(ENRICH, json=request, params={"refDataRelease": SYNTHETIC_RELEASE})
    assert response.status_code == 200, response.text
    assert response.json()["tenantId"] == TENANT_A.value
    refused = await api.client.post(ENRICH, json=body(point(*CENTRE), tenant=TENANT_B))
    assert_problem(refused, 403, "forbidden")


async def test_an_unregistered_tenant_is_refused(api: Api) -> None:
    nobody = TenantId("nobody")
    response = await api.enrich(body(point(*CENTRE), tenant=nobody))
    assert_problem(response, 403, "tenant_not_registered")


async def test_tenants_see_only_their_own_and_shared_geofences(api: Api) -> None:
    ops = api.world.ops
    location = point(80.7505, 8.0305)
    params = {"refDataRelease": SYNTHETIC_RELEASE}
    as_a = (await api.enrich(body(location), params=params)).json()
    as_b = (await api.enrich(body(location, tenant=TENANT_B), params=params)).json()
    assert {hit["id"] for hit in as_a["geofenceHits"]} == {str(ops.polygon_fence), str(ops.circle_fence)}
    assert {hit["id"] for hit in as_b["geofenceHits"]} == {
        str(ops.b_private_fence),
        str(ops.b_authority_fence),
    }
    assert str(ops.camera_b1) not in {device["deviceId"] for device in as_a["nearestDevices"]}
    shared = await api.enrich(body(point(80.71, 8.06)), params=params)
    assert {(hit["id"], hit["tenantId"]) for hit in shared.json()["geofenceHits"]} == {
        (str(ops.b_shared_fence), TENANT_B.value)
    }


# --- errors ----------------------------------------------------------------------------------------------


async def test_swapped_coordinates_are_explained(api: Api) -> None:
    request = body(point(8.0305, 80.7505))
    problem = assert_problem(await api.enrich(request), 422, "invalid_coordinate")
    assert problem["likelySwapped"] is True
    assert problem["position"] == [8.0305, 80.7505]
    assert "[longitude, latitude]" in problem["detail"]
    assert await stored_locations(api.world, TENANT_A, request["eventId"]) == 0


async def test_invalid_polygons_are_explained(api: Api) -> None:
    bow_tie = {
        "type": "Polygon",
        "coordinates": [[[80.70, 8.0], [80.8, 8.1], [80.8, 8.0], [80.7, 8.1], [80.70, 8.0]]],
    }
    problem = assert_problem(await api.enrich(body(bow_tie)), 422, "invalid_geometry")
    assert problem["reason"].startswith("Self-intersection")


async def test_unknown_devices_and_releases_are_not_found(api: Api) -> None:
    device = body(None, sourceType="device", locationSource="device", deviceId=str(uuid.uuid4()))
    assert_problem(await api.enrich(device), 404, "device_not_found")
    release = await api.enrich(body(point(*CENTRE)), params={"refDataRelease": "ref-1999.01"})
    assert assert_problem(release, 404, "release_not_found")["refDataRelease"] == "ref-1999.01"


async def test_devices_of_other_tenants_cannot_report(api: Api) -> None:
    shared = body(
        None, sourceType="device", locationSource="device", deviceId=str(api.world.ops.camera_b2_shared)
    )
    problem = assert_problem(await api.enrich(shared), 422, "validation_error")
    assert "reporting tenant" in problem["detail"]


async def test_draft_releases_cannot_be_used(api: Api) -> None:
    async with transaction(api.world.migrator_sessions) as session:
        await session.execute(text("INSERT INTO meta.ref_data_release (code) VALUES ('ref-2026.11-draft')"))
    response = await api.enrich(body(point(*CENTRE)), params={"refDataRelease": "ref-2026.11-draft"})
    problem = assert_problem(response, 422, "release_not_usable")
    assert (problem["refDataRelease"], problem["releaseStatus"]) == ("ref-2026.11-draft", "draft")


async def test_missing_current_release_is_a_503(api: Api) -> None:
    async with transaction(api.world.migrator_sessions) as session:
        await session.execute(text("UPDATE meta.ref_data_release SET is_current = false WHERE is_current"))
    try:
        response = await api.enrich(body(point(*CENTRE)))
    finally:
        async with transaction(api.world.migrator_sessions) as session:
            await session.execute(
                text("UPDATE meta.ref_data_release SET is_current = true WHERE code = :code"),
                {"code": OPEN_RELEASE},
            )
    problem = assert_problem(response, 503, "reference_data_unavailable")
    assert "publish" in problem["detail"]
