"""The spatial query API end to end: layers, features, proximity, containment and reverse geocoding.

Answers are checked against the constructed fixture world (``data/fixtures/synthetic_habarana``), whose
geometry has known relationships, and against distances the database itself computes. Tenant-scoped
layers are queried as two different tenants, so what row-level security hides is part of the assertions.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Final

import pytest
from sqlalchemy import text

from app.db.session import transaction
from tests.integration.api_client import Api, api_client_for, assert_problem, feature_names, ok
from tests.integration.conftest import SpatialWorld
from tests.integration.distances import distance_to, latitude_at_distance
from tests.integration.spatial_world import (
    AUTHORITY,
    CENTRE,
    OPEN_RELEASE,
    SYNTHETIC_RELEASE,
    TENANT_A,
    TENANT_B,
)

LAYERS: Final = "/geo/v1/layers"
WITHIN_DISTANCE: Final = "/geo/v1/query/within-distance"
NEAREST: Final = "/geo/v1/query/nearest"
CONTAINS: Final = "/geo/v1/query/contains"
REVERSE: Final = "/geo/v1/reverse"

SYNTHETIC: Final = {"refDataRelease": SYNTHETIC_RELEASE}
VILLAGE: Final = (80.71, 8.06)
TOWN_CENTRE: Final = (80.750, 8.032)  # inside the Fixture Town footprint, north of the DS boundary
MULTI_ZONE_POINT: Final = (80.758, 8.015)
PARK_ENCLAVE: Final = (80.775, 8.055)
DISTRICT_BOUNDARY: Final = (80.75, 8.005)
THRESHOLD_M: Final = 500.0


def features_path(layer: str) -> str:
    return f"{LAYERS}/{layer}/features"


def point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Positions 499 m, 500 m and 501 m from a target, found with the database's transformation."""

    positions: dict[tuple[str, float], tuple[float, float]]
    exact: dict[tuple[str, float], float]


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    async with api_client_for(spatial_world) as client:
        yield client


@pytest.fixture(scope="module")
async def thresholds(spatial_world: SpatialWorld) -> Thresholds:
    positions: dict[tuple[str, float], tuple[float, float]] = {}
    exact: dict[tuple[str, float], float] = {}
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        targets = {
            "settlement": (
                await session.scalar(
                    text(
                        "SELECT public.ST_AsEWKB(s.geom_metric) FROM ref.settlement AS s "
                        "JOIN meta.ref_data_release AS r ON r.id = s.release_id "
                        "WHERE r.code = :code AND s.name = 'Fixture Village'"
                    ),
                    {"code": SYNTHETIC_RELEASE},
                ),
                *VILLAGE,
            ),
            "circle_geofence": (
                await session.scalar(
                    text(
                        "SELECT public.ST_AsEWKB(definition_geom_metric) FROM ops.geofence "
                        "WHERE name = 'Fixture Circle Fence'"
                    )
                ),
                *CENTRE,
            ),
        }
        for name, (ewkb, lon, lat) in targets.items():
            for metres in (THRESHOLD_M - 1, THRESHOLD_M, THRESHOLD_M + 1):
                found = await latitude_at_distance(session, bytes(ewkb), lon, lat, lat + 0.01, metres)
                positions[name, metres] = (lon, found)
                exact[name, metres] = await distance_to(session, bytes(ewkb), lon, found)
    return Thresholds(positions=positions, exact=exact)


# --- the catalogue ---------------------------------------------------------------------------------------


async def test_the_catalogue_lists_the_layers_and_what_can_be_asked_of_them(api: Api) -> None:
    body = ok(await api.get(LAYERS))

    layers = {layer["code"]: layer for layer in body["layers"]}
    assert {"ref.admin_area", "ref.settlement", "ref.road", "ops.geofence", "ops.device"} <= set(layers)
    settlement = layers["ref.settlement"]
    assert settlement["queryable"] is True
    assert settlement["tenantScoped"] is False
    assert settlement["srid"] == 4326
    assert settlement["metricSrid"] == 5235
    assert "within_distance" in settlement["capabilities"]
    assert "type" in settlement["filters"]
    assert "settlementType" in settlement["properties"]
    assert layers["ops.geofence"]["tenantScoped"] is True
    assert layers["ops.geofence"]["timeFiltered"] is True
    assert "contains" in layers["ops.geofence"]["capabilities"]
    # A line layer answers proximity questions but not containment.
    assert "contains" not in layers["ref.road"]["capabilities"]
    assert body["refDataRelease"] == OPEN_RELEASE


async def test_the_catalogue_covers_every_registered_layer(api: Api) -> None:
    body = ok(await api.get(LAYERS))

    async with transaction(api.world.app_sessions) as session:
        registered = set(
            (await session.execute(text("SELECT code FROM meta.layer WHERE is_published"))).scalars().all()
        )
    assert {layer["code"] for layer in body["layers"]} == registered


async def test_reading_the_catalogue_needs_no_credentials(api: Api) -> None:
    """The main platform owns sign-in: the GIS answers without a token or a tenant header."""
    response = await api.client.get(LAYERS)

    ok(response)
    assert "www-authenticate" not in response.headers


# --- features of a layer ---------------------------------------------------------------------------------


async def test_features_are_geojson_filtered_by_viewport_and_attribute(api: Api) -> None:
    body = ok(
        await api.get(
            features_path("ref.settlement"),
            params={**SYNTHETIC, "bbox": "80.74,8.02,80.76,8.04", "type": "town"},
        )
    )

    assert body["type"] == "FeatureCollection"
    assert feature_names(body) == ["Fixture Town"]
    feature = body["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "MultiPolygon"
    assert feature["properties"]["settlementType"] == "town"
    assert feature["properties"]["population"] == 4200
    assert body["layer"] == "ref.settlement"
    assert body["refDataRelease"] == SYNTHETIC_RELEASE
    assert body["nextCursor"] is None
    assert body["count"] == 1


async def test_a_viewport_leaves_out_what_is_outside_it(api: Api) -> None:
    body = ok(
        await api.get(
            features_path("ref.settlement"), params={**SYNTHETIC, "bbox": "80.700,8.050,80.720,8.070"}
        )
    )

    assert feature_names(body) == ["Fixture Village"]


async def test_features_can_be_searched_by_name(api: Api) -> None:
    body = ok(await api.get(features_path("ref.road"), params={**SYNTHETIC, "nameContains": "track"}))

    assert feature_names(body) == ["Fixture Track"]


async def test_features_can_be_returned_without_their_geometry(api: Api) -> None:
    body = ok(await api.get(features_path("ref.admin_area"), params={**SYNTHETIC, "includeGeometry": False}))

    assert body["features"]
    assert all(feature["geometry"] is None for feature in body["features"])


async def test_features_are_paged_with_a_cursor(api: Api) -> None:
    params = {**SYNTHETIC, "limit": 1, "includeGeometry": False}

    first = ok(await api.get(features_path("ref.admin_area"), params=params))
    assert first["count"] == 1
    assert first["nextCursor"]

    second = ok(
        await api.get(features_path("ref.admin_area"), params={**params, "cursor": first["nextCursor"]})
    )
    assert second["count"] == 1
    assert second["features"][0]["id"] != first["features"][0]["id"]

    seen: set[str] = set()
    cursor: str | None = None
    for _ in range(20):
        page = ok(
            await api.get(
                features_path("ref.admin_area"), params={**params, "cursor": cursor} if cursor else params
            )
        )
        seen.update(feature["id"] for feature in page["features"])
        cursor = page["nextCursor"]
        if cursor is None:
            break
    assert cursor is None
    assert len(seen) == 8  # the fixture world has eight administrative areas


async def test_a_cursor_cannot_be_used_with_other_filters(api: Api) -> None:
    first = ok(await api.get(features_path("ref.admin_area"), params={**SYNTHETIC, "limit": 1}))

    response = await api.get(
        features_path("ref.admin_area"),
        params={**SYNTHETIC, "limit": 1, "level": 2, "cursor": first["nextCursor"]},
    )

    assert_problem(response, 422, "invalid_cursor")


async def test_an_unknown_layer_is_not_found(api: Api) -> None:
    response = await api.get(features_path("ref.nonexistent"), params=SYNTHETIC)

    problem = assert_problem(response, 404, "layer_not_found")
    assert "ref.settlement" in problem["queryableLayers"]


async def test_a_layer_code_that_is_not_a_layer_code_is_rejected(api: Api) -> None:
    response = await api.get(features_path("ref.settlement; DROP TABLE ref.settlement"), params=SYNTHETIC)

    assert_problem(response, 422, "request_validation_error")


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"level": 2}, "unsupported_filter"),
        ({"type": "metropolis"}, "unsupported_filter"),
        ({"at": "2026-09-10T00:00:00Z"}, "unsupported_filter"),
        ({"bbox": "80.7,8.0"}, "invalid_bbox"),
        ({"bbox": "80.8,8.0,80.7,8.1"}, "invalid_bbox"),
    ],
)
async def test_a_filter_the_layer_does_not_have_is_refused(
    api: Api, params: dict[str, Any], code: str
) -> None:
    response = await api.get(features_path("ref.settlement"), params={**SYNTHETIC, **params})

    problem = assert_problem(response, 422, code)
    if code == "unsupported_filter":
        assert problem["layer"] == "ref.settlement"


async def test_a_layer_with_a_validity_period_is_read_as_of_an_instant(api: Api) -> None:
    during = ok(
        await api.get(
            features_path("ref.risk_zone"),
            params={**SYNTHETIC, "at": "2025-11-15T00:00:00Z", "type": "flood"},
        )
    )
    after = ok(
        await api.get(
            features_path("ref.risk_zone"),
            params={**SYNTHETIC, "at": "2026-03-15T00:00:00Z", "type": "flood"},
        )
    )

    assert feature_names(during) == ["Fixture Flood Zone"]
    assert after["features"] == []


async def test_a_tenant_layer_cannot_be_read_for_another_tenant(api: Api) -> None:
    response = await api.get(
        features_path("ops.geofence"), tenant=TENANT_A, params={"tenantId": TENANT_B.value}
    )

    assert_problem(response, 403, "forbidden")


async def test_a_tenant_sees_its_own_and_shared_features_only(api: Api) -> None:
    for_a = ok(await api.get(features_path("ops.geofence"), tenant=TENANT_A))
    for_b = ok(await api.get(features_path("ops.geofence"), tenant=TENANT_B))

    assert "Fixture Circle Fence" in feature_names(for_a)
    assert "Fixture B Shared Fence" in feature_names(for_a)  # shared with tenant A
    assert "Fixture B Private Fence" not in feature_names(for_a)
    assert "Fixture Circle Fence" not in feature_names(for_b)
    assert {feature["properties"]["tenantId"] for feature in for_b["features"]} == {TENANT_B.value}


async def test_paging_a_time_filtered_layer_reads_one_state_of_it(api: Api) -> None:
    """Without an explicit `at` every request would otherwise read the layer as of its own "now"."""
    params = {"limit": 1, "includeGeometry": False, "status": "active"}

    first = ok(await api.get(features_path("ops.geofence"), tenant=TENANT_A, params=params))
    assert first["nextCursor"]
    second = ok(
        await api.get(
            features_path("ops.geofence"),
            tenant=TENANT_A,
            params={**params, "cursor": first["nextCursor"]},
        )
    )

    assert second["count"] == 1
    assert second["features"][0]["id"] != first["features"][0]["id"]


async def test_a_release_cannot_be_asked_for_on_tenant_data(api: Api) -> None:
    response = await api.get(features_path("ops.geofence"), tenant=TENANT_A, params={**SYNTHETIC})

    problem = assert_problem(response, 422, "unsupported_filter")
    assert problem["filter"] == "refDataRelease"


async def test_a_cursor_cannot_be_carried_to_another_tenant(api: Api) -> None:
    """A cursor belongs to the tenant it was made for."""
    params = {"limit": 1, "includeGeometry": False}
    first = ok(await api.get(features_path("ops.geofence"), tenant=TENANT_A, params=params))

    response = await api.get(
        features_path("ops.geofence"), tenant=TENANT_B, params={**params, "cursor": first["nextCursor"]}
    )

    assert_problem(response, 422, "invalid_cursor")


async def test_a_tenant_must_be_the_one_the_request_acts_for(api: Api) -> None:
    response = await api.get(
        features_path("ops.geofence"), tenant=TENANT_A, params={"tenantId": TENANT_B.value}
    )

    problem = assert_problem(response, 403, "forbidden")
    assert problem["tenantId"] == TENANT_B.value


# --- objects within a distance ---------------------------------------------------------------------------


async def test_objects_within_a_distance_come_back_nearest_first_with_their_distance(api: Api) -> None:
    body = ok(
        await api.post(
            WITHIN_DISTANCE,
            json={
                "target": "ref.facility",
                "geometry": point(*TOWN_CENTRE),
                "distanceM": 5000,
                **SYNTHETIC,
            },
        )
    )

    assert feature_names(body) == ["Fixture Police Station", "Fixture Wildlife Office"]
    distances = [feature["properties"]["distanceM"] for feature in body["features"]]
    assert distances == sorted(distances)
    assert all(distance <= 5000 for distance in distances)
    assert body["refDataRelease"] == SYNTHETIC_RELEASE


async def test_a_distance_is_measured_to_the_feature_and_rounded_to_a_centimetre(api: Api) -> None:
    body = ok(
        await api.post(
            WITHIN_DISTANCE,
            json={
                "target": "ref.settlement",
                "geometry": point(*TOWN_CENTRE),
                "distanceM": 1000,
                "filters": {"type": "town"},
                **SYNTHETIC,
            },
        )
    )

    town = body["features"][0]
    assert town["properties"]["name"] == "Fixture Town"
    # The point lies inside the town footprint, so the distance to it is zero.
    assert town["properties"]["distanceM"] == 0.0


@pytest.mark.parametrize("metres", [THRESHOLD_M - 1, THRESHOLD_M])
async def test_a_feature_at_or_within_the_distance_is_included(
    api: Api, thresholds: Thresholds, metres: float
) -> None:
    lon, lat = thresholds.positions["settlement", metres]

    body = ok(
        await api.post(
            WITHIN_DISTANCE,
            json={
                "target": "ref.settlement",
                "geometry": point(lon, lat),
                "distanceM": THRESHOLD_M,
                **SYNTHETIC,
            },
        )
    )

    assert "Fixture Village" in feature_names(body)
    found = next(f for f in body["features"] if f["properties"]["name"] == "Fixture Village")
    assert found["properties"]["distanceM"] == pytest.approx(
        round(thresholds.exact["settlement", metres], 2), abs=0.01
    )


async def test_a_feature_beyond_the_distance_is_left_out(api: Api, thresholds: Thresholds) -> None:
    lon, lat = thresholds.positions["settlement", THRESHOLD_M + 1]

    body = ok(
        await api.post(
            WITHIN_DISTANCE,
            json={
                "target": "ref.settlement",
                "geometry": point(lon, lat),
                "distanceM": THRESHOLD_M,
                **SYNTHETIC,
            },
        )
    )

    assert "Fixture Village" not in feature_names(body)


async def test_objects_within_a_distance_are_paged(api: Api) -> None:
    query = {
        "target": "ref.admin_area",
        "geometry": point(*TOWN_CENTRE),
        "distanceM": 50_000,
        "limit": 3,
        "includeGeometry": False,
        **SYNTHETIC,
    }

    first = ok(await api.post(WITHIN_DISTANCE, json=query))
    assert first["count"] == 3
    second = ok(await api.post(WITHIN_DISTANCE, json={**query, "cursor": first["nextCursor"]}))

    assert second["count"] > 0
    assert not set(f["id"] for f in first["features"]) & set(f["id"] for f in second["features"])
    distances = [f["properties"]["distanceM"] for f in first["features"] + second["features"]]
    assert distances == sorted(distances)


async def test_devices_near_a_point_are_the_tenants_own(api: Api) -> None:
    query = {"target": "ops.device", "geometry": point(*CENTRE), "distanceM": 5000}

    for_a = ok(await api.post(WITHIN_DISTANCE, json=query, tenant=TENANT_A))
    for_b = ok(await api.post(WITHIN_DISTANCE, json=query, tenant=TENANT_B))

    assert "Fixture Camera A1" in feature_names(for_a)
    assert "Fixture Camera B2" in feature_names(for_a)  # shared with tenant A
    assert "Fixture Camera B1" not in feature_names(for_a)
    assert "Fixture Camera A1" not in feature_names(for_b)
    assert for_a["refDataRelease"] is None  # operational data has no reference release


async def test_the_distance_to_a_circle_geofence_is_measured_to_its_edge(api: Api) -> None:
    body = ok(
        await api.post(
            WITHIN_DISTANCE,
            json={"target": "ops.geofence", "geometry": point(*CENTRE), "distanceM": 10},
            tenant=TENANT_A,
        )
    )

    circle = next(f for f in body["features"] if f["properties"]["name"] == "Fixture Circle Fence")
    assert circle["properties"]["distanceM"] == 0.0  # the centre lies inside it
    assert circle["properties"]["geofenceKind"] == "circle"
    assert circle["properties"]["radiusM"] == 500.0


# --- nearest objects -------------------------------------------------------------------------------------


async def test_the_nearest_objects_come_back_in_order(api: Api) -> None:
    body = ok(
        await api.post(
            NEAREST,
            json={
                "target": "ref.settlement",
                "geometry": point(*VILLAGE),
                "limit": 2,
                "maxDistanceM": 25_000,
                **SYNTHETIC,
            },
        )
    )

    assert feature_names(body) == ["Fixture Village", "Fixture Town"]
    assert body["features"][0]["properties"]["distanceM"] == 0.0
    assert body["nextCursor"] is None


async def test_nearest_does_not_look_beyond_the_bound(api: Api) -> None:
    body = ok(
        await api.post(
            NEAREST,
            json={"target": "ref.settlement", "geometry": point(*VILLAGE), "maxDistanceM": 100, **SYNTHETIC},
        )
    )

    assert feature_names(body) == ["Fixture Village"]


async def test_nearest_respects_the_limit(api: Api) -> None:
    body = ok(
        await api.post(
            NEAREST,
            json={"target": "ref.admin_area", "geometry": point(*TOWN_CENTRE), "limit": 1, **SYNTHETIC},
        )
    )

    assert body["count"] == 1


# --- containment -----------------------------------------------------------------------------------------


async def test_the_areas_that_contain_a_point_are_returned_with_their_relation(api: Api) -> None:
    body = ok(
        await api.post(
            CONTAINS,
            json={"target": "ref.risk_zone", "geometry": point(*MULTI_ZONE_POINT), **SYNTHETIC},
        )
    )

    assert sorted(feature_names(body)) == ["Fixture Drought Zone", "Fixture Elephant Corridor"]
    assert {f["properties"]["relation"] for f in body["features"]} == {"within"}
    assert body["refDataRelease"] == SYNTHETIC_RELEASE


async def test_a_point_in_an_enclave_is_outside_the_area_around_it(api: Api) -> None:
    inside = ok(
        await api.post(
            CONTAINS, json={"target": "ref.protected_area", "geometry": point(80.765, 8.045), **SYNTHETIC}
        )
    )
    enclave = ok(
        await api.post(
            CONTAINS, json={"target": "ref.protected_area", "geometry": point(*PARK_ENCLAVE), **SYNTHETIC}
        )
    )

    assert feature_names(inside) == ["Fixture National Park"]
    assert enclave["features"] == []


async def test_a_point_on_a_boundary_lies_in_both_areas(api: Api) -> None:
    body = ok(
        await api.post(
            CONTAINS,
            json={
                "target": "ref.admin_area",
                "geometry": point(*DISTRICT_BOUNDARY),
                "filters": {"level": 2},
                **SYNTHETIC,
            },
        )
    )

    assert sorted(f["properties"]["code"] for f in body["features"]) == ["SYN-D1", "SYN-D2"]


async def test_a_line_that_crosses_a_boundary_intersects_but_is_not_covered(api: Api) -> None:
    crossing = {"type": "LineString", "coordinates": [[80.755, 8.010], [80.800, 8.010]]}

    covers = ok(await api.post(CONTAINS, json={"target": "ref.risk_zone", "geometry": crossing, **SYNTHETIC}))
    intersects = ok(
        await api.post(
            CONTAINS,
            json={"target": "ref.risk_zone", "geometry": crossing, "mode": "intersects", **SYNTHETIC},
        )
    )

    assert "Fixture Elephant Corridor" not in feature_names(covers)
    assert "Fixture Elephant Corridor" in feature_names(intersects)
    corridor = next(
        f for f in intersects["features"] if f["properties"]["name"] == "Fixture Elephant Corridor"
    )
    assert corridor["properties"]["relation"] == "intersects"


async def test_overlapping_zones_are_all_returned(api: Api) -> None:
    body = ok(
        await api.post(
            CONTAINS, json={"target": "ref.risk_zone", "geometry": point(*MULTI_ZONE_POINT), **SYNTHETIC}
        )
    )

    # Two risk zones overlap here; both contain the point, and neither hides the other.
    assert sorted(feature_names(body)) == ["Fixture Drought Zone", "Fixture Elephant Corridor"]
    assert {feature["properties"]["relation"] for feature in body["features"]} == {"within"}


@pytest.mark.parametrize(
    ("path", "query"),
    [
        (WITHIN_DISTANCE, {"target": "ref.settlement", "distanceM": 500}),
        (NEAREST, {"target": "ref.settlement", "maxDistanceM": 500}),
        (CONTAINS, {"target": "ref.protected_area"}),
    ],
)
async def test_an_empty_answer_is_an_empty_collection(api: Api, path: str, query: dict[str, Any]) -> None:
    # Open country in the south of the service area, far from every fixture feature.
    body = ok(await api.post(path, json={**query, "geometry": point(81.5, 6.5), **SYNTHETIC}))

    assert body["type"] == "FeatureCollection"
    assert (body["features"], body["count"], body.get("nextCursor")) == ([], 0, None)
    assert body["refDataRelease"] == SYNTHETIC_RELEASE


async def test_containment_is_only_asked_of_layers_with_areas(api: Api) -> None:
    response = await api.post(
        CONTAINS, json={"target": "ref.road", "geometry": point(*TOWN_CENTRE), **SYNTHETIC}
    )

    problem = assert_problem(response, 422, "unsupported_query")
    assert problem["layer"] == "ref.road"


@pytest.mark.parametrize("metres", [THRESHOLD_M - 1, THRESHOLD_M])
async def test_a_circle_geofence_contains_a_point_at_or_inside_its_radius(
    api: Api, thresholds: Thresholds, metres: float
) -> None:
    lon, lat = thresholds.positions["circle_geofence", metres]

    body = ok(
        await api.post(
            CONTAINS, json={"target": "ops.geofence", "geometry": point(lon, lat)}, tenant=TENANT_A
        )
    )

    assert "Fixture Circle Fence" in feature_names(body)


async def test_a_circle_geofence_does_not_contain_a_point_beyond_its_radius(
    api: Api, thresholds: Thresholds
) -> None:
    lon, lat = thresholds.positions["circle_geofence", THRESHOLD_M + 1]

    body = ok(
        await api.post(
            CONTAINS, json={"target": "ops.geofence", "geometry": point(lon, lat)}, tenant=TENANT_A
        )
    )

    assert "Fixture Circle Fence" not in feature_names(body)


async def test_a_circle_geofence_covers_an_area_that_fits_inside_it(api: Api) -> None:
    """For an area the test is the farthest point from the centre, not a polygon approximation."""
    inside = {
        "type": "Polygon",
        "coordinates": [
            [[80.7495, 8.0295], [80.7505, 8.0295], [80.7505, 8.0305], [80.7495, 8.0305], [80.7495, 8.0295]]
        ],
    }
    straddling = {
        "type": "Polygon",
        "coordinates": [
            [[80.7495, 8.0295], [80.7505, 8.0295], [80.7505, 8.0400], [80.7495, 8.0400], [80.7495, 8.0295]]
        ],
    }

    covered = ok(
        await api.post(CONTAINS, json={"target": "ops.geofence", "geometry": inside}, tenant=TENANT_A)
    )
    partly = ok(
        await api.post(CONTAINS, json={"target": "ops.geofence", "geometry": straddling}, tenant=TENANT_A)
    )
    touching = ok(
        await api.post(
            CONTAINS,
            json={"target": "ops.geofence", "geometry": straddling, "mode": "intersects"},
            tenant=TENANT_A,
        )
    )

    assert "Fixture Circle Fence" in feature_names(covered)
    assert "Fixture Circle Fence" not in feature_names(partly)
    assert "Fixture Circle Fence" in feature_names(touching)
    circle = next(f for f in touching["features"] if f["properties"]["name"] == "Fixture Circle Fence")
    assert circle["properties"]["relation"] == "intersects"


async def test_containment_of_geofences_stays_within_the_tenant(api: Api) -> None:
    query = {"target": "ops.geofence", "geometry": point(*CENTRE)}

    for_a = ok(await api.post(CONTAINS, json=query, tenant=TENANT_A))
    for_b = ok(await api.post(CONTAINS, json=query, tenant=TENANT_B))
    for_authority = ok(await api.post(CONTAINS, json=query, tenant=AUTHORITY))

    assert "Fixture Polygon Fence" in feature_names(for_a)
    assert "Fixture B Private Fence" not in feature_names(for_a)
    assert "Fixture B Private Fence" in feature_names(for_b)
    assert "Fixture Polygon Fence" not in feature_names(for_b)
    # An authority tenant sees what is shared with authorities, and nothing that is private.
    assert "Fixture B Authority Fence" in feature_names(for_authority)
    assert "Fixture B Private Fence" not in feature_names(for_authority)


async def test_archived_and_future_geofences_are_still_described_by_their_status(api: Api) -> None:
    body = ok(await api.get(features_path("ops.geofence"), tenant=TENANT_A, params={"status": "archived"}))

    assert feature_names(body) == ["Fixture Archived Fence"]


# --- geometry and CRS validation -------------------------------------------------------------------------


async def test_an_invalid_geometry_is_refused_with_the_reason(api: Api) -> None:
    bow_tie = {
        "type": "Polygon",
        "coordinates": [
            [[80.785, 7.985], [80.795, 7.995], [80.795, 7.985], [80.785, 7.995], [80.785, 7.985]]
        ],
    }

    response = await api.post(
        CONTAINS, json={"target": "ref.protected_area", "geometry": bow_tie, **SYNTHETIC}
    )

    problem = assert_problem(response, 422, "invalid_geometry")
    assert "Self-intersection" in problem["reason"]


async def test_a_position_outside_the_service_area_is_refused(api: Api) -> None:
    response = await api.post(
        NEAREST, json={"target": "ref.settlement", "geometry": point(2.35, 48.85), **SYNTHETIC}
    )

    problem = assert_problem(response, 422, "invalid_coordinate")
    assert problem["serviceAreaBbox"]


async def test_swapped_axes_are_named_as_the_likely_mistake(api: Api) -> None:
    response = await api.post(
        NEAREST, json={"target": "ref.settlement", "geometry": point(8.03, 80.75), **SYNTHETIC}
    )

    problem = assert_problem(response, 422, "invalid_coordinate")
    assert problem["likelySwapped"] is True


@pytest.mark.parametrize("crs", ["EPSG:4326", "CRS84", "urn:ogc:def:crs:OGC::CRS84"])
async def test_a_wgs84_crs_may_be_stated(api: Api, crs: str) -> None:
    body = ok(
        await api.post(
            NEAREST,
            json={"target": "ref.settlement", "geometry": point(*VILLAGE), "crs": crs, **SYNTHETIC},
        )
    )

    assert body["count"] >= 1


async def test_any_other_crs_is_refused(api: Api) -> None:
    response = await api.post(
        NEAREST,
        json={"target": "ref.settlement", "geometry": point(*VILLAGE), "crs": "EPSG:5235", **SYNTHETIC},
    )

    problem = assert_problem(response, 422, "request_validation_error")
    assert "WGS84" in str(problem["errors"])


async def test_a_geojson_crs_member_is_not_accepted(api: Api) -> None:
    geometry = {**point(*VILLAGE), "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}}

    response = await api.post(NEAREST, json={"target": "ref.settlement", "geometry": geometry, **SYNTHETIC})

    assert_problem(response, 422, "request_validation_error")


async def test_a_geometry_collection_is_not_accepted(api: Api) -> None:
    geometry = {"type": "GeometryCollection", "geometries": [point(*VILLAGE)]}

    response = await api.post(NEAREST, json={"target": "ref.settlement", "geometry": geometry, **SYNTHETIC})

    assert_problem(response, 422, "request_validation_error")


# --- reverse geocoding -----------------------------------------------------------------------------------


async def test_reverse_geocoding_describes_where_a_position_is(api: Api) -> None:
    body = ok(
        await api.get(REVERSE, params={"lon": TOWN_CENTRE[0] - 0.002, "lat": TOWN_CENTRE[1], **SYNTHETIC})
    )

    admin = body["admin"]
    assert admin["province"]["code"] == "SYN-P1"
    assert admin["district"]["code"] == "SYN-D1"
    assert admin["dsDivision"]["code"] == "SYN-S2"
    assert admin["codes"]["l1"] == "SYN-P1"
    assert body["nearestSettlement"]["name"] == "Fixture Town"
    assert body["nearestSettlement"]["distanceM"] == 0.0  # inside the footprint
    assert body["nearestRoad"]["name"] == "Fixture Road"
    assert body["nearestRoad"]["distanceM"] > 0
    assert body["refDataRelease"] == SYNTHETIC_RELEASE
    assert body["point"] == point(TOWN_CENTRE[0] - 0.002, TOWN_CENTRE[1])
    assert body["missingLayers"] == []


async def test_reverse_geocoding_names_the_area_on_a_boundary_deterministically(api: Api) -> None:
    first = ok(await api.get(REVERSE, params={"lon": CENTRE[0], "lat": CENTRE[1], **SYNTHETIC}))
    again = ok(await api.get(REVERSE, params={"lon": CENTRE[0], "lat": CENTRE[1], **SYNTHETIC}))

    assert first["admin"]["onBoundary"] is True
    assert first["admin"]["district"]["code"] == "SYN-D1"  # the lowest code of the two
    assert first["admin"] == again["admin"]


async def test_reverse_geocoding_uses_the_current_release_by_default(api: Api) -> None:
    body = ok(await api.get(REVERSE, params={"lon": 80.7513, "lat": 8.0342}))

    assert body["refDataRelease"] == OPEN_RELEASE
    assert body["admin"]["district"] is not None


async def test_reverse_geocoding_refuses_a_position_outside_the_service_area(api: Api) -> None:
    response = await api.get(REVERSE, params={"lon": 2.35, "lat": 48.85})

    problem = assert_problem(response, 422, "invalid_coordinate")
    assert problem["serviceAreaBbox"] == [79.44, 5.66, 82.15, 10.08]


async def test_reverse_geocoding_rejects_a_position_that_is_not_a_position(api: Api) -> None:
    response = await api.get(REVERSE, params={"lon": 200.0, "lat": 8.03})

    assert_problem(response, 422, "request_validation_error")


async def test_reverse_geocoding_reports_an_unknown_release(api: Api) -> None:
    response = await api.get(REVERSE, params={"lon": 80.75, "lat": 8.03, "refDataRelease": "ref-2000.01"})

    problem = assert_problem(response, 404, "release_not_found")
    assert problem["refDataRelease"] == "ref-2000.01"


async def test_reverse_geocoding_needs_no_tenant(api: Api) -> None:
    body = ok(await api.get(REVERSE, params={"lon": 80.75, "lat": 8.03, **SYNTHETIC}))

    assert body["admin"]["province"]["code"] == "SYN-P1"


# --- the boundary of this service ------------------------------------------------------------------------


FORBIDDEN_WORDS: Final = ("notify", "notification", "recipient", "alert", "subscriber", "sms")
SPATIAL_OPERATIONS: Final = (
    "listLayers",
    "listLayerFeatures",
    "queryWithinDistance",
    "queryNearest",
    "queryContains",
    "reverseGeocode",
    "listEvents",
    "listGeofences",
    "createGeofence",
    "getGeofence",
    "replaceGeofence",
    "deleteGeofence",
    "listSites",
    "createSite",
    "getSite",
    "replaceSite",
    "deleteSite",
    "getDevicePlacement",
    "putDevicePlacement",
)


async def test_the_api_offers_no_recipient_or_notification_endpoint(api: Api) -> None:
    """The GIS service answers spatial questions; nothing in it addresses people (ADR-0012)."""
    schema = ok(await api.client.get("/openapi.json"))

    paths = " ".join(schema["paths"]).lower()
    for word in FORBIDDEN_WORDS:
        assert word not in paths


async def test_the_spatial_endpoints_are_documented_without_a_word_about_messaging(api: Api) -> None:
    schema = ok(await api.client.get("/openapi.json"))

    documented = {
        operation["operationId"]: f"{operation.get('summary', '')} {operation.get('description', '')}"
        for path in schema["paths"].values()
        for operation in path.values()
        if "operationId" in operation
    }
    assert set(SPATIAL_OPERATIONS) <= set(documented)
    for name in SPATIAL_OPERATIONS:
        for word in FORBIDDEN_WORDS:
            assert word not in documented[name].lower(), f"{name} mentions {word!r}"


async def test_a_device_id_is_never_a_person(api: Api) -> None:
    """Device proximity answers "which cameras are near this", not "who is near this"."""
    body = ok(await api.get(LAYERS))

    properties = {p for layer in body["layers"] for p in layer["properties"]}
    assert not {"person", "user", "phone", "msisdn", "subscriber"} & properties


def test_the_fixture_world_is_the_one_these_tests_assume(spatial_world: SpatialWorld) -> None:
    assert spatial_world.synthetic.release_code == SYNTHETIC_RELEASE
    assert uuid.UUID(str(spatial_world.ops.circle_fence))
