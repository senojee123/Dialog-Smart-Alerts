"""Exact distances from the database, for tests about thresholds.

A test that asserts "499 m is inside and 501 m is outside" has to place its positions with the same
transformation the service uses, or it only tests the test's own geodesy. These helpers ask PostGIS for
the EPSG:5235 distance and find a position at a given distance by bisection over doubles, so the
distance the service computes is the distance the test intends.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DISTANCE_SQL: Final = (
    "SELECT public.ST_Distance(public.ST_GeomFromEWKB(:target), public.ST_Transform("
    "public.ST_SetSRID(public.ST_MakePoint(CAST(:lon AS double precision), CAST(:lat AS double precision)), "
    "4326), 5235))"
)
DISTANCE = text(DISTANCE_SQL)


async def distance_to(session: AsyncSession, target_ewkb: bytes, lon: float, lat: float) -> float:
    """Metres (EPSG:5235) between the target geometry and the position, as the database computes it."""
    value = await session.scalar(DISTANCE, {"target": target_ewkb, "lon": lon, "lat": lat})
    return float(value)


async def latitude_at_distance(
    session: AsyncSession, target_ewkb: bytes, lon: float, lat_near: float, lat_far: float, metres: float
) -> float:
    """The largest latitude (doubles) north of the target whose database distance is at most ``metres``."""
    near, far = lat_near, lat_far
    assert await distance_to(session, target_ewkb, lon, near) <= metres
    assert await distance_to(session, target_ewkb, lon, far) > metres
    while True:
        middle = (near + far) / 2
        if middle <= near or middle >= far:
            return near
        if await distance_to(session, target_ewkb, lon, middle) <= metres:
            near = middle
        else:
            far = middle
