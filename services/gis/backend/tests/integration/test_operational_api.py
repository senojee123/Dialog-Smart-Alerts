"""Geofences, sites and device placements over HTTP: what a tenant may change, and what it may not.

The geometry a caller defines is what gets stored (and what hits are tested against), versions guard
against overwriting someone else's edit, and row-level security decides what another tenant can see or
change - which is asserted from both sides.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from app.core.tenancy import TenantId
from app.schemas.events import EventLocationIn
from app.services.enrichment import GeoContextLimits, GeoContextService
from tests.integration.api_client import Api, api_client_for, assert_problem, ok
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import AUTHORITY, SYNTHETIC_RELEASE, TENANT_A, TENANT_B

GEOFENCES: Final = "/geo/v1/geofences"
SITES: Final = "/geo/v1/sites"
_ids = iter(range(1, 1_000_000))

# Somewhere quiet in the fixture world, away from the geofences the fixtures create.
AREA: Final = [[80.720, 7.990], [80.730, 7.990], [80.730, 8.000], [80.720, 8.000], [80.720, 7.990]]
CENTRE_POINT: Final = (80.7250, 7.9950)
LINE: Final = [[80.720, 7.995], [80.730, 7.995]]


def unique(prefix: str) -> str:
    return f"{prefix}-{next(_ids)}"


def polygon(ring: list[list[float]] | None = None) -> dict[str, Any]:
    return {"type": "Polygon", "coordinates": [ring or AREA]}


def point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


def geofence_body(**fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": unique("Test Fence"),
        "definition": {"kind": "polygon", "geometry": polygon()},
        "status": "active",
    }
    body.update(fields)
    return body


def site_body(**fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": unique("Test Site"),
        "position": point(*CENTRE_POINT),
        "positionSource": "gps",
        "positionAccuracyM": 3.5,
    }
    body.update(fields)
    return body


def placement_body(**fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": unique("Test Camera"),
        "deviceType": "camera",
        "position": point(*CENTRE_POINT),
        "positionSource": "gps",
    }
    body.update(fields)
    return body


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    async with api_client_for(spatial_world) as client:
        yield client


async def create_geofence(api: Api, **fields: Any) -> dict[str, Any]:
    response = await api.post(GEOFENCES, json=geofence_body(**fields), tenant=TENANT_A)
    return ok(response, 201)


async def create_site(api: Api, **fields: Any) -> dict[str, Any]:
    return ok(await api.post(SITES, json=site_body(**fields), tenant=TENANT_A), 201)


def placement_path(device_id: uuid.UUID | str) -> str:
    return f"/geo/v1/devices/{device_id}/placement"


# --- creating geofences ----------------------------------------------------------------------------------


async def test_a_polygon_geofence_stores_the_geometry_that_was_defined(api: Api) -> None:
    body = await create_geofence(api, description="A test area")

    assert body["definition"]["kind"] == "polygon"
    assert body["definition"]["geometry"] == polygon()
    assert body["definition"]["radiusM"] is None
    assert body["areaM2"] > 0
    assert body["version"] == 1
    assert body["tenantId"] == TENANT_A.value
    assert body["status"] == "active"
    assert body["sharingPolicy"] == "private"
    assert body["createdBy"] is not None
    assert body["effectiveDuring"]["from"] is not None
    assert body["effectiveDuring"]["to"] is None


async def test_a_created_geofence_is_readable_at_the_location_it_reports(api: Api) -> None:
    created = await create_geofence(api)

    response = await api.get(f"{GEOFENCES}/{created['id']}", tenant=TENANT_A)

    assert ok(response) == created


async def test_a_circle_geofence_keeps_its_centre_and_radius(api: Api) -> None:
    body = await create_geofence(
        api, definition={"kind": "circle", "geometry": point(*CENTRE_POINT), "radiusM": 250}
    )

    assert body["definition"] == {"kind": "circle", "geometry": point(*CENTRE_POINT), "radiusM": 250.0}
    assert body["areaM2"] == pytest.approx(3.14159265 * 250**2, rel=1e-6)


async def test_a_corridor_geofence_keeps_its_centre_line_and_half_width(api: Api) -> None:
    body = await create_geofence(
        api,
        definition={
            "kind": "corridor",
            "geometry": {"type": "LineString", "coordinates": LINE},
            "radiusM": 40,
        },
    )

    assert body["definition"]["kind"] == "corridor"
    assert body["definition"]["geometry"]["coordinates"] == LINE
    assert body["definition"]["radiusM"] == 40.0
    assert body["areaM2"] > 0


async def test_a_geofence_is_created_with_the_attributes_it_was_given(api: Api) -> None:
    body = await create_geofence(api, attributes={"owner": "ranger team", "priority": 2})

    assert body["attributes"] == {"owner": "ranger team", "priority": 2}


async def test_a_geofence_may_be_created_for_a_period(api: Api) -> None:
    period = {"from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"}

    body = await create_geofence(api, effectiveDuring=period)

    assert body["effectiveDuring"] == period


@pytest.mark.parametrize(
    ("definition", "code"),
    [
        pytest.param(
            {
                "kind": "polygon",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[80.785, 7.985], [80.795, 7.995], [80.795, 7.985], [80.785, 7.995], [80.785, 7.985]]
                    ],
                },
            },
            "invalid_geometry",
            id="self-intersecting polygon",
        ),
        pytest.param(
            {"kind": "circle", "geometry": point(2.35, 48.85), "radiusM": 100},
            "invalid_coordinate",
            id="outside the service area",
        ),
        pytest.param(
            {"kind": "circle", "geometry": point(8.03, 80.75), "radiusM": 100},
            "invalid_coordinate",
            id="swapped axes",
        ),
    ],
)
async def test_a_geofence_geometry_is_validated(api: Api, definition: dict[str, Any], code: str) -> None:
    response = await api.post(GEOFENCES, json=geofence_body(definition=definition), tenant=TENANT_A)

    assert_problem(response, 422, code)


@pytest.mark.parametrize(
    "definition",
    [
        {"kind": "circle", "geometry": polygon(), "radiusM": 100},
        {"kind": "polygon", "geometry": polygon(), "radiusM": 100},
        {"kind": "corridor", "geometry": point(*CENTRE_POINT), "radiusM": 100},
        {"kind": "corridor", "geometry": {"type": "LineString", "coordinates": LINE}, "radiusM": 6000},
        {"kind": "circle", "geometry": point(*CENTRE_POINT)},
    ],
)
async def test_a_definition_that_does_not_match_its_kind_is_refused(
    api: Api, definition: dict[str, Any]
) -> None:
    response = await api.post(GEOFENCES, json=geofence_body(definition=definition), tenant=TENANT_A)

    assert_problem(response, 422, "request_validation_error")


async def test_an_external_id_belongs_to_one_geofence_per_tenant(api: Api) -> None:
    external_id = unique("external")
    await create_geofence(api, externalId=external_id)

    response = await api.post(GEOFENCES, json=geofence_body(externalId=external_id), tenant=TENANT_A)

    problem = assert_problem(response, 409, "external_id_in_use")
    assert problem["constraint"] == "uq_geofence_tenant_id_external_id"


async def test_a_tenant_the_gis_service_does_not_know_is_reported_as_such(api: Api) -> None:
    """A request may act for a tenant that was never registered here; that is a 403, not a 500."""
    stranger = TenantId("unregistered-tenant")

    response = await api.post(GEOFENCES, json=geofence_body(), tenant=stranger)

    assert_problem(response, 403, "tenant_not_registered")


# --- listing geofences -----------------------------------------------------------------------------------


async def test_geofences_are_listed_with_their_filters(api: Api) -> None:
    created = await create_geofence(
        api, definition={"kind": "circle", "geometry": point(*CENTRE_POINT), "radiusM": 120}
    )

    body = ok(
        await api.get(GEOFENCES, tenant=TENANT_A, params={"kind": "circle", "nameContains": created["name"]})
    )

    assert [item["id"] for item in body["items"]] == [created["id"]]
    assert body["count"] == 1
    assert body["nextCursor"] is None


async def test_geofences_can_be_listed_by_viewport_and_status(api: Api) -> None:
    created = await create_geofence(api, status="draft")

    inside = ok(
        await api.get(GEOFENCES, tenant=TENANT_A, params={"bbox": "80.71,7.98,80.74,8.01", "status": "draft"})
    )
    outside = ok(
        await api.get(GEOFENCES, tenant=TENANT_A, params={"bbox": "80.60,7.60,80.62,7.62", "status": "draft"})
    )

    assert created["id"] in [item["id"] for item in inside["items"]]
    assert outside["items"] == []


async def test_a_status_that_does_not_exist_is_refused(api: Api) -> None:
    response = await api.get(GEOFENCES, tenant=TENANT_A, params={"status": "retired"})

    problem = assert_problem(response, 422, "unsupported_filter")
    assert "archived" in problem["allowedValues"]


async def test_a_site_filter_does_not_apply_to_geofences(api: Api) -> None:
    response = await api.get(GEOFENCES, tenant=TENANT_A, params={"siteType": "pole"})

    assert_problem(response, 422, "unsupported_filter")


async def test_geofences_are_listed_as_of_an_instant(api: Api) -> None:
    created = await create_geofence(
        api, effectiveDuring={"from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"}
    )

    during = ok(await api.get(GEOFENCES, tenant=TENANT_A, params={"at": "2026-10-15T00:00:00Z"}))
    after = ok(await api.get(GEOFENCES, tenant=TENANT_A, params={"at": "2026-12-15T00:00:00Z"}))

    assert created["id"] in [item["id"] for item in during["items"]]
    assert created["id"] not in [item["id"] for item in after["items"]]


async def test_geofences_are_paged(api: Api) -> None:
    for _ in range(3):
        await create_geofence(api)

    first = ok(await api.get(GEOFENCES, tenant=TENANT_A, params={"limit": 2}))
    second = ok(await api.get(GEOFENCES, tenant=TENANT_A, params={"limit": 2, "cursor": first["nextCursor"]}))

    assert first["count"] == 2
    assert second["count"] > 0
    first_ids = {item["id"] for item in first["items"]}
    assert not first_ids & {item["id"] for item in second["items"]}


# --- changing geofences ----------------------------------------------------------------------------------


async def test_a_geofence_is_replaced_on_the_version_it_was_read_at(api: Api) -> None:
    created = await create_geofence(api)
    moved = [[80.740, 7.990], [80.745, 7.990], [80.745, 7.995], [80.740, 7.995], [80.740, 7.990]]

    body = ok(
        await api.put(
            f"{GEOFENCES}/{created['id']}",
            json=geofence_body(
                name=created["name"],
                definition={"kind": "polygon", "geometry": polygon(moved)},
                version=created["version"],
            ),
            tenant=TENANT_A,
        )
    )

    assert body["version"] == created["version"] + 1
    assert body["definition"]["geometry"] == polygon(moved)
    assert body["updatedBy"] is not None
    assert body["id"] == created["id"]


async def test_a_stale_version_is_refused_instead_of_overwriting(api: Api) -> None:
    created = await create_geofence(api)
    update = geofence_body(name=created["name"], version=created["version"])
    ok(await api.put(f"{GEOFENCES}/{created['id']}", json=update, tenant=TENANT_A))

    response = await api.put(f"{GEOFENCES}/{created['id']}", json=update, tenant=TENANT_A)

    problem = assert_problem(response, 409, "version_conflict")
    assert problem["currentVersion"] == created["version"] + 1


async def test_changing_a_geofence_that_does_not_exist_is_not_found(api: Api) -> None:
    response = await api.put(f"{GEOFENCES}/{uuid.uuid4()}", json=geofence_body(version=1), tenant=TENANT_A)

    assert_problem(response, 404, "geofence_not_found")


# --- retiring geofences ----------------------------------------------------------------------------------


async def test_deleting_a_geofence_archives_it(api: Api) -> None:
    created = await create_geofence(api)

    response = await api.delete(f"{GEOFENCES}/{created['id']}", tenant=TENANT_A)

    assert response.status_code == 204, response.text
    after = ok(await api.get(f"{GEOFENCES}/{created['id']}", tenant=TENANT_A))
    assert after["status"] == "archived"
    assert after["version"] == created["version"] + 1


async def test_a_geofence_may_be_purged_for_good(api: Api) -> None:
    created = await create_geofence(api)

    response = await api.delete(f"{GEOFENCES}/{created['id']}", params={"purge": True}, tenant=TENANT_A)

    assert response.status_code == 204, response.text
    assert_problem(await api.get(f"{GEOFENCES}/{created['id']}", tenant=TENANT_A), 404, "geofence_not_found")


async def test_retiring_a_geofence_can_be_made_conditional(api: Api) -> None:
    created = await create_geofence(api)

    response = await api.delete(f"{GEOFENCES}/{created['id']}", params={"version": 99}, tenant=TENANT_A)

    assert_problem(response, 409, "version_conflict")


# --- sharing and isolation -------------------------------------------------------------------------------


async def test_a_shared_geofence_can_be_read_by_the_tenant_it_is_shared_with(api: Api) -> None:
    created = await create_geofence(api, sharingPolicy="shared", sharedWithTenants=[TENANT_B.value])

    body = ok(await api.get(f"{GEOFENCES}/{created['id']}", tenant=TENANT_B))

    assert body["id"] == created["id"]
    assert body["tenantId"] == TENANT_A.value
    assert body["sharedWithTenants"] == [TENANT_B.value]


async def test_a_shared_geofence_can_still_only_be_changed_by_its_owner(api: Api) -> None:
    created = await create_geofence(api, sharingPolicy="shared", sharedWithTenants=[TENANT_B.value])

    response = await api.put(
        f"{GEOFENCES}/{created['id']}",
        json=geofence_body(version=created["version"]),
        tenant=TENANT_B,
    )

    problem = assert_problem(response, 403, "not_owner")
    assert problem["ownerTenantId"] == TENANT_A.value


async def test_a_shared_geofence_cannot_be_deleted_by_the_tenant_it_is_shared_with(api: Api) -> None:
    created = await create_geofence(api, sharingPolicy="shared", sharedWithTenants=[TENANT_B.value])

    response = await api.delete(f"{GEOFENCES}/{created['id']}", tenant=TENANT_B)

    assert_problem(response, 403, "not_owner")
    assert ok(await api.get(f"{GEOFENCES}/{created['id']}", tenant=TENANT_A))["status"] == "active"


async def test_a_private_geofence_of_another_tenant_is_not_even_there(api: Api) -> None:
    created = await create_geofence(api)

    assert_problem(await api.get(f"{GEOFENCES}/{created['id']}", tenant=TENANT_B), 404, "geofence_not_found")
    assert_problem(
        await api.delete(f"{GEOFENCES}/{created['id']}", tenant=TENANT_B),
        404,
        "geofence_not_found",
    )


async def test_a_geofence_shared_with_authorities_is_readable_by_an_authority(api: Api) -> None:
    created = await create_geofence(api, sharingPolicy="authority_only")

    assert ok(await api.get(f"{GEOFENCES}/{created['id']}", tenant=AUTHORITY))["id"] == created["id"]
    assert_problem(await api.get(f"{GEOFENCES}/{created['id']}", tenant=TENANT_B), 404, "geofence_not_found")


async def test_only_tenants_may_be_named_as_readers(api: Api) -> None:
    response = await api.post(
        GEOFENCES,
        json=geofence_body(sharingPolicy="private", sharedWithTenants=[TENANT_B.value]),
        tenant=TENANT_A,
    )

    assert_problem(response, 422, "request_validation_error")


# --- a created geofence is what enrichment tests against -------------------------------------------------


async def test_a_geofence_created_here_is_what_an_event_is_tested_against(api: Api) -> None:
    created = await create_geofence(
        api,
        definition={"kind": "circle", "geometry": point(*CENTRE_POINT), "radiusM": 300},
        effectiveDuring={"from": "2026-09-01T00:00:00Z"},
    )
    service = GeoContextService(api.world.app_sessions, api.world.service_area, GeoContextLimits())

    context = await service.enrich(
        EventLocationIn.model_validate(
            {
                "eventId": unique("evt"),
                "tenantId": TENANT_A.value,
                "observedAt": datetime(2026, 9, 10, 12, tzinfo=UTC).isoformat(),
                "eventType": "wildlife.elephant_detected",
                "sourceType": "sensor",
                "locationSource": "sensor",
                "location": point(*CENTRE_POINT),
            }
        ),
        release_code=SYNTHETIC_RELEASE,
    )

    hits = {hit.id: hit for hit in context.geofence_hits}
    assert uuid.UUID(created["id"]) in hits
    hit = hits[uuid.UUID(created["id"])]
    assert hit.kind == "circle"
    assert hit.version == created["version"]
    assert hit.relation == "within"
    assert hit.tenant_id == TENANT_A.value


# --- sites ------------------------------------------------------------------------------------------------


async def test_a_site_is_created_read_and_listed(api: Api) -> None:
    created = await create_site(api, siteType="pole")

    assert created["position"] == point(*CENTRE_POINT)
    assert created["siteType"] == "pole"
    assert created["status"] == "active"
    assert created["positionAccuracyM"] == 3.5
    assert ok(await api.get(f"{SITES}/{created['id']}", tenant=TENANT_A)) == created
    listed = ok(await api.get(SITES, tenant=TENANT_A, params={"nameContains": created["name"]}))
    assert [item["id"] for item in listed["items"]] == [created["id"]]


async def test_a_site_position_must_be_a_point(api: Api) -> None:
    response = await api.post(SITES, json=site_body(position=polygon()), tenant=TENANT_A)

    assert_problem(response, 422, "request_validation_error")


async def test_a_site_is_replaced_on_its_version(api: Api) -> None:
    created = await create_site(api)
    moved = point(80.7260, 7.9960)

    body = ok(
        await api.put(
            f"{SITES}/{created['id']}",
            json=site_body(name=created["name"], position=moved, version=created["version"]),
            tenant=TENANT_A,
        )
    )

    assert body["position"] == moved
    assert body["version"] == created["version"] + 1


async def test_deleting_a_site_decommissions_it(api: Api) -> None:
    created = await create_site(api)

    response = await api.delete(f"{SITES}/{created['id']}", tenant=TENANT_A)

    assert response.status_code == 204, response.text
    assert ok(await api.get(f"{SITES}/{created['id']}", tenant=TENANT_A))["status"] == "decommissioned"


async def test_a_site_of_another_tenant_is_not_visible(api: Api) -> None:
    created = await create_site(api)

    assert_problem(await api.get(f"{SITES}/{created['id']}", tenant=TENANT_B), 404, "site_not_found")


# --- device placement -------------------------------------------------------------------------------------


async def test_a_device_is_registered_by_putting_its_placement(api: Api) -> None:
    device_id = uuid.uuid4()

    body = ok(
        await api.put(placement_path(device_id), json=placement_body(), tenant=TENANT_A),
        201,
    )

    assert body["id"] == str(device_id)
    assert body["position"] == point(*CENTRE_POINT)
    assert body["version"] == 1
    assert body["fieldOfView"] is None
    assert body["tenantId"] == TENANT_A.value


async def test_putting_a_placement_again_moves_the_device(api: Api) -> None:
    device_id = uuid.uuid4()
    created = ok(
        await api.put(placement_path(device_id), json=placement_body(), tenant=TENANT_A),
        201,
    )
    moved = point(80.7255, 7.9955)

    body = ok(
        await api.put(
            placement_path(device_id),
            json=placement_body(name=created["name"], position=moved, version=created["version"]),
            tenant=TENANT_A,
        )
    )

    assert body["position"] == moved
    assert body["version"] == created["version"] + 1
    assert ok(await api.get(placement_path(device_id), tenant=TENANT_A))["position"] == moved


async def test_a_placement_that_exists_needs_the_version_it_was_read_at(api: Api) -> None:
    device_id = uuid.uuid4()
    created = ok(
        await api.put(placement_path(device_id), json=placement_body(), tenant=TENANT_A),
        201,
    )

    without_version = await api.put(
        placement_path(device_id),
        json=placement_body(name=created["name"]),
        tenant=TENANT_A,
    )
    stale = await api.put(
        placement_path(device_id),
        json=placement_body(name=created["name"], version=99),
        tenant=TENANT_A,
    )

    assert_problem(without_version, 409, "version_conflict")
    assert_problem(stale, 409, "version_conflict")


async def test_a_version_cannot_be_given_for_a_device_that_does_not_exist_yet(api: Api) -> None:
    response = await api.put(placement_path(uuid.uuid4()), json=placement_body(version=1), tenant=TENANT_A)

    assert_problem(response, 409, "version_conflict")


async def test_a_modelled_field_of_view_is_computed_by_the_service(api: Api) -> None:
    device_id = uuid.uuid4()
    field_of_view = {"method": "modelled", "bearingDeg": 90, "fovDeg": 60, "rangeM": 200}

    body = ok(
        await api.put(
            placement_path(device_id),
            json=placement_body(fieldOfView=field_of_view),
            tenant=TENANT_A,
        ),
        201,
    )

    view = body["fieldOfView"]
    assert view["method"] == "modelled"
    assert view["bearingDeg"] == 90.0
    assert view["rangeM"] == 200.0
    assert view["geometry"]["type"] == "MultiPolygon"
    assert view["validDuring"]["to"] is None


async def test_a_surveyed_field_of_view_is_stored_as_given(api: Api) -> None:
    device_id = uuid.uuid4()
    observed = polygon([[80.724, 7.994], [80.727, 7.994], [80.727, 7.997], [80.724, 7.997], [80.724, 7.994]])

    body = ok(
        await api.put(
            placement_path(device_id),
            json=placement_body(fieldOfView={"method": "surveyed", "geometry": observed}),
            tenant=TENANT_A,
        ),
        201,
    )

    view = body["fieldOfView"]
    assert view["method"] == "surveyed"
    assert view["geometry"]["coordinates"] == [observed["coordinates"]]


async def test_replacing_a_field_of_view_closes_the_one_in_effect(api: Api) -> None:
    device_id = uuid.uuid4()
    created = ok(
        await api.put(
            placement_path(device_id),
            json=placement_body(
                fieldOfView={"method": "modelled", "bearingDeg": 0, "fovDeg": 45, "rangeM": 100}
            ),
            tenant=TENANT_A,
        ),
        201,
    )
    first_view = created["fieldOfView"]

    replaced = ok(
        await api.put(
            placement_path(device_id),
            json=placement_body(
                name=created["name"],
                version=created["version"],
                fieldOfView={"method": "modelled", "bearingDeg": 180, "fovDeg": 45, "rangeM": 100},
            ),
            tenant=TENANT_A,
        )
    )

    view = replaced["fieldOfView"]
    assert view["id"] != first_view["id"]
    assert view["bearingDeg"] == 180.0
    assert view["validDuring"]["from"] >= first_view["validDuring"]["from"]
    earlier = ok(
        await api.get(
            placement_path(device_id),
            tenant=TENANT_A,
            params={"at": first_view["validDuring"]["from"]},
        )
    )
    assert earlier["fieldOfView"]["id"] == first_view["id"]


async def test_a_modelled_field_of_view_follows_the_device_when_it_moves(api: Api) -> None:
    device_id = uuid.uuid4()
    created = ok(
        await api.put(
            placement_path(device_id),
            json=placement_body(
                fieldOfView={"method": "modelled", "bearingDeg": 0, "fovDeg": 90, "rangeM": 150}
            ),
            tenant=TENANT_A,
        ),
        201,
    )

    moved = ok(
        await api.put(
            placement_path(device_id),
            json=placement_body(
                name=created["name"], position=point(80.7270, 7.9970), version=created["version"]
            ),
            tenant=TENANT_A,
        )
    )

    assert moved["fieldOfView"]["id"] == created["fieldOfView"]["id"]
    assert moved["fieldOfView"]["geometry"] != created["fieldOfView"]["geometry"]


async def test_a_placement_may_name_a_site_of_the_same_tenant(api: Api) -> None:
    site = await create_site(api)
    device_id = uuid.uuid4()

    body = ok(
        await api.put(
            placement_path(device_id),
            json=placement_body(siteId=site["id"], mountingHeightM=6.5),
            tenant=TENANT_A,
        ),
        201,
    )

    assert body["siteId"] == site["id"]
    assert body["mountingHeightM"] == 6.5


async def test_a_placement_cannot_name_a_site_of_another_tenant(api: Api) -> None:
    site = await create_site(api)

    response = await api.put(
        placement_path(uuid.uuid4()),
        json=placement_body(siteId=site["id"]),
        tenant=TENANT_B,
    )

    assert_problem(response, 422, "unknown_site")


async def test_a_device_of_another_tenant_is_neither_readable_nor_movable(api: Api) -> None:
    device_id = uuid.uuid4()
    created = ok(
        await api.put(placement_path(device_id), json=placement_body(), tenant=TENANT_A),
        201,
    )

    # A private device of another tenant is not visible at all, so the placement cannot be read...
    assert_problem(await api.get(placement_path(device_id), tenant=TENANT_B), 404, "device_not_found")
    # ... and neither a change based on its version nor a fresh registration under its id gets through.
    with_version = await api.put(
        placement_path(device_id),
        json=placement_body(name=created["name"], version=created["version"]),
        tenant=TENANT_B,
    )
    assert_problem(with_version, 409, "version_conflict")
    without_version = await api.put(placement_path(device_id), json=placement_body(), tenant=TENANT_B)
    assert_problem(without_version, 409, "identifier_in_use")
    assert ok(await api.get(placement_path(device_id), tenant=TENANT_A))["name"] == created["name"]


async def test_a_shared_device_is_readable_but_not_movable_by_the_other_tenant(api: Api) -> None:
    body = ok(await api.get(placement_path(api.world.ops.camera_b2_shared), tenant=TENANT_A))

    assert body["tenantId"] == TENANT_B.value
    response = await api.put(
        placement_path(api.world.ops.camera_b2_shared),
        json=placement_body(name=body["name"], version=body["version"]),
        tenant=TENANT_A,
    )
    assert_problem(response, 403, "not_owner")


async def test_a_placement_cannot_be_read_for_another_tenant(api: Api) -> None:
    response = await api.get(
        placement_path(api.world.ops.camera_a1), tenant=TENANT_A, params={"tenantId": TENANT_B.value}
    )

    assert_problem(response, 403, "forbidden")
