"""Spatial regression tests in the database (plan Section 14).

These pin the behaviour every spatial feature relies on: the PostGIS version, the SLD99 grid
definition, agreement between database and application transformations, and exact distance
thresholds in metres.
"""

from __future__ import annotations

import math

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.repositories.database_info import DatabaseInfoRepository
from app.spatial import crs

ORIGIN_LAT = 7 + 0 / 60 + 1.6975 / 3600
ORIGIN_LON = 80 + 46 / 60 + 18.1671 / 3600

PROBES = [(79.64, 5.86), (81.95, 5.86), (81.95, 9.88), (79.64, 9.88), (79.8612, 6.9271), (81.2152, 8.3114)]


async def test_postgis_meets_the_minimum_version(
    migrated_database: Settings, app_engine: AsyncEngine
) -> None:
    async with app_engine.connect() as connection:
        info = await DatabaseInfoRepository(connection).postgis_info()
    assert info is not None
    major, minor = (int(part) for part in info.lib_version.split(".")[:2])
    assert (major, minor) >= migrated_database.postgis_min_version_tuple


async def test_sld99_grid_origin_in_database(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as connection:
        x, y = await DatabaseInfoRepository(connection).transform_point(
            ORIGIN_LON, ORIGIN_LAT, crs.SLD99_GEOGRAPHIC, crs.SLD99_GRID
        )
    assert x == pytest.approx(500_000.0, abs=0.005)
    assert y == pytest.approx(500_000.0, abs=0.005)


@pytest.mark.parametrize(("lon", "lat"), PROBES)
async def test_database_and_application_transform_identically(
    migrated_database: Settings, app_engine: AsyncEngine, lon: float, lat: float
) -> None:
    async with app_engine.connect() as connection:
        db_x, db_y = await DatabaseInfoRepository(connection).transform_point(
            lon, lat, crs.WGS84, crs.SLD99_GRID
        )
    app_x, app_y = crs.wgs84_to_metric_xy(lon, lat)
    assert math.hypot(db_x - app_x, db_y - app_y) <= migrated_database.crs_consistency_tolerance_m


DWITHIN = text(
    """
    WITH origin AS (
        SELECT ST_Transform(ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                                    CAST(:lat AS double precision)), 4326), 5235) AS g
    )
    SELECT
        ST_DWithin(o.g,
                   ST_Translate(o.g, CAST(:offset AS double precision), 0),
                   CAST(:threshold AS double precision)) AS within,
        ST_Distance(o.g, ST_Translate(o.g, CAST(:offset AS double precision), 0)) AS distance_m
    FROM origin o
    """
)


@pytest.mark.parametrize(
    ("offset_m", "expected"),
    [(499.0, True), (499.999, True), (500.0, True), (500.001, False), (501.0, False)],
)
async def test_500_m_threshold_is_exact_in_the_metric_crs(
    app_engine: AsyncEngine, offset_m: float, expected: bool
) -> None:
    """ST_DWithin is inclusive; rules such as "within 500 m of a settlement" depend on that (plan S-01)."""
    async with app_engine.connect() as connection:
        row = (
            await connection.execute(
                DWITHIN, {"lon": ORIGIN_LON, "lat": ORIGIN_LAT, "offset": offset_m, "threshold": 500.0}
            )
        ).one()
    assert row.within is expected
    assert row.distance_m == pytest.approx(offset_m, abs=1e-6)


GEODESIC_VS_GRID = text(
    """
    WITH p AS (
        SELECT
            ST_SetSRID(
                ST_MakePoint(CAST(:lon1 AS double precision), CAST(:lat1 AS double precision)), 4326
            ) AS a,
            ST_SetSRID(
                ST_MakePoint(CAST(:lon2 AS double precision), CAST(:lat2 AS double precision)), 4326
            ) AS b
    )
    SELECT ST_Distance(a::geography, b::geography) AS geodesic_m,
           ST_Distance(ST_Transform(a, 5235), ST_Transform(b, 5235)) AS grid_m
    FROM p
    """
)


@pytest.mark.parametrize(
    ("lon1", "lat1", "lon2", "lat2"), [(79.8612, 6.9271, 79.8660, 6.9300), (81.20, 8.30, 81.25, 8.35)]
)
async def test_grid_distance_matches_geodesic_distance(
    app_engine: AsyncEngine, lon1: float, lat1: float, lon2: float, lat2: float
) -> None:
    async with app_engine.connect() as connection:
        row = (
            await connection.execute(
                GEODESIC_VS_GRID, {"lon1": lon1, "lat1": lat1, "lon2": lon2, "lat2": lat2}
            )
        ).one()
    assert abs(row.grid_m - row.geodesic_m) <= row.geodesic_m * 250e-6
