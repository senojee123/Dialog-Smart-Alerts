"""Spatial regression tests: the answers are compared with the database's own arithmetic.

Each test asks the query repository a question and asks PostgreSQL the same question in a different way -
by scanning every row, by computing the distance directly, by sorting the whole layer. The two must
agree. That catches a wrong operator, a missed transformation or an index that silently changes an
answer, which a fixture-based expectation would not.

The index checks are the other half of the same concern: a predicate that cannot use the spatial index
still returns the right answer, only slowly, and under row-level security that is exactly what a
non-leakproof operator causes (ADR-0014). They run with sequential scans disabled, so a plan that still
falls back to one is a real finding rather than a cost estimate on small tables.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

import pytest
import shapely
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.paging import fetch_limit
from app.db.session import transaction
from app.repositories.spatial_query import (
    ContainmentQuery,
    DistanceQuery,
    EventQuery,
    FeatureQuery,
    SpatialQueryRepository,
    containment_statement,
    distance_statement,
    events_statement,
    features_statement,
)
from app.spatial.layers import LAYERS_BY_CODE
from tests.integration.conftest import SpatialWorld
from tests.integration.distances import distance_to, latitude_at_distance
from tests.integration.spatial_world import CENTRE, SYNTHETIC_RELEASE, TENANT_A

PROBE: Final = (80.7480, 8.0280)
MULTI_ZONE_POINT: Final = (80.758, 8.015)
ROAD_LATITUDE: Final = 8.01
THRESHOLD_M: Final = 500.0
SEARCH_M: Final = 40_000.0


def wkb(lon: float, lat: float) -> bytes:
    return bytes(shapely.to_wkb(shapely.Point(lon, lat), output_dimension=2))


async def release_id(session: AsyncSession) -> uuid.UUID:
    value = await session.scalar(
        text("SELECT id FROM meta.ref_data_release WHERE code = :code"), {"code": SYNTHETIC_RELEASE}
    )
    return uuid.UUID(str(value))


async def brute_force_distances(
    session: AsyncSession, table: str, lon: float, lat: float, metres: float
) -> list[tuple[str, float]]:
    """Name and distance of every feature of the release within ``metres``, computed row by row."""
    statement = text(
        f"""
        SELECT t.name, public.ST_Distance(t.geom_metric, p.geom_metric) AS distance_m
        FROM {table} AS t,
             (SELECT public.ST_Transform(
                 public.ST_SetSRID(public.ST_MakePoint(:lon, :lat), 4326), 5235) AS geom_metric) AS p
        WHERE t.release_id = :release_id
          AND public.ST_Distance(t.geom_metric, p.geom_metric) <= :metres
        ORDER BY 2, t.name COLLATE "C"
        """  # noqa: S608 - the table name comes from the registry, not from a request
    )
    rows = (
        await session.execute(
            statement,
            {"lon": lon, "lat": lat, "metres": metres, "release_id": await release_id(session)},
        )
    ).all()
    return [(row.name, float(row.distance_m)) for row in rows]


# --- proximity -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("layer_code", ["ref.settlement", "ref.facility", "ref.road", "ref.admin_area"])
async def test_within_distance_finds_what_a_row_by_row_scan_finds(
    spatial_world: SpatialWorld, layer_code: str
) -> None:
    layer = LAYERS_BY_CODE[layer_code]
    async with transaction(spatial_world.app_sessions) as session:
        expected = await brute_force_distances(session, layer.table, *PROBE, SEARCH_M)
        rows = await SpatialQueryRepository(session).within_distance(
            DistanceQuery(
                layer=layer,
                limit=1000,
                geometry_wkb=wkb(*PROBE),
                distance_m=SEARCH_M,
                release_id=await release_id(session),
                include_geometry=False,
            )
        )

    # Features at the same distance may come back in either order, so compare by distance and name.
    found = sorted((round(row.distance_m or 0.0, 6), row.properties["name"]) for row in rows)
    assert found == sorted((round(distance, 6), name) for name, distance in expected)
    assert [row.distance_m for row in rows] == sorted(row.distance_m or 0.0 for row in rows)


async def test_nearest_is_the_start_of_the_sorted_layer(spatial_world: SpatialWorld) -> None:
    layer = LAYERS_BY_CODE["ref.settlement"]
    async with transaction(spatial_world.app_sessions) as session:
        everything = await brute_force_distances(session, layer.table, *PROBE, SEARCH_M)
        rows = await SpatialQueryRepository(session).within_distance(
            DistanceQuery(
                layer=layer,
                limit=2,
                geometry_wkb=wkb(*PROBE),
                distance_m=SEARCH_M,
                release_id=await release_id(session),
                include_geometry=False,
            )
        )

    assert [row.properties["name"] for row in rows] == [name for name, _ in everything[:2]]


@pytest.mark.parametrize("metres", [THRESHOLD_M - 1, THRESHOLD_M, THRESHOLD_M + 1])
async def test_a_distance_threshold_is_inclusive_to_the_metre(
    spatial_world: SpatialWorld, metres: float
) -> None:
    """499 m and 500 m are inside a 500 m search; 501 m is not."""
    async with transaction(spatial_world.app_sessions) as session:
        target = bytes(
            await session.scalar(
                text(
                    "SELECT public.ST_AsEWKB(r.geom_metric) FROM ref.road AS r "
                    "JOIN meta.ref_data_release AS l ON l.id = r.release_id "
                    "WHERE l.code = :code AND r.name = 'Fixture Road'"
                ),
                {"code": SYNTHETIC_RELEASE},
            )
        )
        latitude = await latitude_at_distance(
            session, target, PROBE[0], ROAD_LATITUDE, ROAD_LATITUDE + 0.01, metres
        )
        exact = await distance_to(session, target, PROBE[0], latitude)
        rows = await SpatialQueryRepository(session).within_distance(
            DistanceQuery(
                layer=LAYERS_BY_CODE["ref.road"],
                limit=10,
                geometry_wkb=wkb(PROBE[0], latitude),
                distance_m=THRESHOLD_M,
                release_id=await release_id(session),
                include_geometry=False,
            )
        )

    names = [row.properties["name"] for row in rows]
    if metres <= THRESHOLD_M:
        assert "Fixture Road" in names
        assert exact <= THRESHOLD_M
    else:
        assert "Fixture Road" not in names
        assert exact > THRESHOLD_M


async def test_the_distance_to_a_circle_geofence_is_the_distance_to_its_edge(
    spatial_world: SpatialWorld,
) -> None:
    layer = LAYERS_BY_CODE["ops.geofence"]
    probe = (CENTRE[0], CENTRE[1] + 0.02)  # a couple of kilometres north of the circle's centre
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        centre = bytes(
            await session.scalar(
                text(
                    "SELECT public.ST_AsEWKB(definition_geom_metric) FROM ops.geofence "
                    "WHERE name = 'Fixture Circle Fence'"
                )
            )
        )
        to_centre = await distance_to(session, centre, *probe)
        rows = await SpatialQueryRepository(session).within_distance(
            DistanceQuery(
                layer=layer,
                limit=50,
                geometry_wkb=wkb(*probe),
                distance_m=SEARCH_M,
                at=_now(),
                include_geometry=False,
            )
        )

    circle = next(row for row in rows if row.properties["name"] == "Fixture Circle Fence")
    assert circle.distance_m == pytest.approx(to_centre - 500.0, abs=0.01)
    assert [row.distance_m for row in rows] == sorted(row.distance_m or 0.0 for row in rows)


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime(2026, 9, 10, 12, tzinfo=UTC)


# --- containment -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("layer_code", ["ref.protected_area", "ref.risk_zone", "ref.admin_area"])
async def test_containment_agrees_with_a_row_by_row_covers_test(
    spatial_world: SpatialWorld, layer_code: str
) -> None:
    layer = LAYERS_BY_CODE[layer_code]
    covering = text(
        f"""
        SELECT t.name
        FROM {layer.table} AS t
        WHERE t.release_id = :release_id
          AND public.ST_Covers(t.geom, public.ST_SetSRID(public.ST_MakePoint(:lon, :lat), 4326))
        ORDER BY t.name COLLATE "C"
        """  # noqa: S608 - the table name comes from the registry, not from a request
    )
    async with transaction(spatial_world.app_sessions) as session:
        release = await release_id(session)
        expected = (
            (
                await session.execute(
                    covering,
                    {"release_id": release, "lon": MULTI_ZONE_POINT[0], "lat": MULTI_ZONE_POINT[1]},
                )
            )
            .scalars()
            .all()
        )
        rows = await SpatialQueryRepository(session).containing(
            ContainmentQuery(
                layer=layer,
                limit=100,
                geometry_wkb=wkb(*MULTI_ZONE_POINT),
                release_id=release,
                at=_now() if layer.period_column else None,
                include_geometry=False,
            )
        )

    assert sorted(row.properties["name"] for row in rows) == sorted(expected)
    assert all(row.relation == "within" for row in rows)


async def test_a_circle_geofence_contains_exactly_what_its_radius_covers(
    spatial_world: SpatialWorld,
) -> None:
    layer = LAYERS_BY_CODE["ops.geofence"]
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        centre = bytes(
            await session.scalar(
                text(
                    "SELECT public.ST_AsEWKB(definition_geom_metric) FROM ops.geofence "
                    "WHERE name = 'Fixture Circle Fence'"
                )
            )
        )
        for metres in (THRESHOLD_M - 1, THRESHOLD_M, THRESHOLD_M + 1):
            latitude = await latitude_at_distance(
                session, centre, CENTRE[0], CENTRE[1], CENTRE[1] + 0.01, metres
            )
            rows = await SpatialQueryRepository(session).containing(
                ContainmentQuery(
                    layer=layer,
                    limit=50,
                    geometry_wkb=wkb(CENTRE[0], latitude),
                    at=_now(),
                    include_geometry=False,
                )
            )
            names = [row.properties["name"] for row in rows]
            inside = await distance_to(session, centre, CENTRE[0], latitude) <= THRESHOLD_M
            assert ("Fixture Circle Fence" in names) is inside, metres


# --- paging ----------------------------------------------------------------------------------------------


async def test_paging_returns_every_row_exactly_once(spatial_world: SpatialWorld) -> None:
    layer = LAYERS_BY_CODE["ref.admin_area"]
    async with transaction(spatial_world.app_sessions) as session:
        release = await release_id(session)
        repository = SpatialQueryRepository(session)
        everything = await repository.features(
            FeatureQuery(layer=layer, limit=1000, release_id=release, include_geometry=False)
        )

        seen: list[uuid.UUID] = []
        after: uuid.UUID | None = None
        while True:
            page = await repository.features(
                FeatureQuery(
                    layer=layer,
                    limit=fetch_limit(2),
                    release_id=release,
                    after_id=after,
                    include_geometry=False,
                )
            )
            rows = page[:2]
            seen.extend(row.id for row in rows)
            if len(page) <= 2:
                break
            after = rows[-1].id

    assert seen == [row.id for row in everything]
    assert len(seen) == len(set(seen))


async def test_paging_by_distance_returns_every_row_exactly_once(spatial_world: SpatialWorld) -> None:
    layer = LAYERS_BY_CODE["ref.admin_area"]
    async with transaction(spatial_world.app_sessions) as session:
        release = await release_id(session)
        repository = SpatialQueryRepository(session)

        def query(limit: int = 1000, **overrides: Any) -> DistanceQuery:
            return DistanceQuery(
                layer=layer,
                limit=limit,
                geometry_wkb=wkb(*PROBE),
                distance_m=SEARCH_M,
                release_id=release,
                include_geometry=False,
                **overrides,
            )

        everything = await repository.within_distance(query())
        seen: list[uuid.UUID] = []
        after: tuple[float, uuid.UUID] | None = None
        while True:
            page = await repository.within_distance(
                query(
                    limit=fetch_limit(2),
                    after_distance_m=None if after is None else after[0],
                    after_id=None if after is None else after[1],
                )
            )
            rows = page[:2]
            seen.extend(row.id for row in rows)
            if len(page) <= 2:
                break
            last = rows[-1]
            assert last.distance_m is not None
            after = (last.distance_m, last.id)

    assert seen == [row.id for row in everything]


# --- index usage -----------------------------------------------------------------------------------------


async def explain(session: AsyncSession, statement: str, params: dict[str, Any]) -> str:
    """The plan for a statement, with sequential scans disabled so an unusable index shows up."""
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (await session.execute(text(f"EXPLAIN {statement}"), params)).scalars().all()
    return "\n".join(plan)


def assert_index_scan(plan: str, table: str) -> None:
    assert "Index Scan" in plan or "Index Only Scan" in plan or "Bitmap Index Scan" in plan, plan
    assert f"Seq Scan on {table}" not in plan, plan


async def test_a_viewport_query_on_reference_data_uses_the_spatial_index(
    spatial_world: SpatialWorld,
) -> None:
    async with transaction(spatial_world.app_sessions) as session:
        statement, params = features_statement(
            FeatureQuery(
                layer=LAYERS_BY_CODE["ref.settlement"],
                limit=100,
                release_id=await release_id(session),
                bbox=(80.70, 7.98, 80.80, 8.08),
            )
        )
        plan = await explain(session, statement, params)

    assert_index_scan(plan, "settlement")


async def test_a_viewport_query_on_tenant_data_uses_the_spatial_index(
    spatial_world: SpatialWorld,
) -> None:
    """Under row-level security an index is used only if the operator is leakproof (ADR-0014)."""
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        statement, params = features_statement(
            FeatureQuery(
                layer=LAYERS_BY_CODE["ops.geofence"],
                limit=100,
                bbox=(80.70, 7.98, 80.80, 8.08),
                at=_now(),
            )
        )
        plan = await explain(session, statement, params)

    assert_index_scan(plan, "geofence")


async def test_a_proximity_query_on_tenant_data_uses_the_spatial_index(
    spatial_world: SpatialWorld,
) -> None:
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        statement, params = distance_statement(
            DistanceQuery(
                layer=LAYERS_BY_CODE["ops.device"], limit=10, geometry_wkb=wkb(*CENTRE), distance_m=5000.0
            )
        )
        plan = await explain(session, statement, params)

    assert_index_scan(plan, "device")


async def test_a_containment_query_uses_the_subdivided_parts(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.app_sessions) as session:
        statement, params = containment_statement(
            ContainmentQuery(
                layer=LAYERS_BY_CODE["ref.protected_area"],
                limit=100,
                geometry_wkb=wkb(*MULTI_ZONE_POINT),
                release_id=await release_id(session),
            )
        )
        plan = await explain(session, statement, params)

    assert "area_part" in plan
    assert_index_scan(plan, "area_part")


async def test_an_event_query_prunes_partitions_and_uses_the_index(spatial_world: SpatialWorld) -> None:
    from datetime import UTC, datetime

    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        statement, params = events_statement(
            EventQuery(
                time_from=datetime(2026, 9, 1, tzinfo=UTC),
                time_to=datetime(2026, 9, 30, tzinfo=UTC),
                limit=50,
                bbox=(80.70, 7.98, 80.80, 8.08),
            )
        )
        plan = await explain(session, statement, params)

    # Only the month in the window is scanned; the other prepared partitions are pruned away.
    assert "event_location_p202609" in plan
    assert "event_location_p202511" not in plan
    assert "Seq Scan on event_location_p202609" not in plan, plan
