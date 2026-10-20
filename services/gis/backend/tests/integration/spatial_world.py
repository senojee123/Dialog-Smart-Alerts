"""The spatial test world: reference data fixtures plus tenant-owned operational data.

Reference data comes from ``data/fixtures`` through the real loader:

* ``lka_open``           open Sri Lankan data (geoBoundaries, Natural Earth), made the current release
* ``synthetic_habarana`` constructed geometry with known answers, a separate published release

Operational data (sites, devices, fields of view, geofences) is created here through the runtime login
with a tenant set, exactly as the API will, so row-level security and triggers apply.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.types import Text

from app.core.config import REPOSITORY_ROOT
from app.core.tenancy import TenantId
from app.db.session import transaction

FIXTURES: Final = REPOSITORY_ROOT / "data" / "fixtures"
OPEN_MANIFEST: Final = FIXTURES / "lka_open" / "manifest.json"
SYNTHETIC_MANIFEST: Final = FIXTURES / "synthetic_habarana" / "manifest.json"
OPEN_RELEASE: Final = "ref-2026.09-lka-open"
SYNTHETIC_RELEASE: Final = "ref-2026.09-fixture"

TENANT_A: Final = TenantId("fixture-tenant-a")
TENANT_B: Final = TenantId("fixture-tenant-b")
AUTHORITY: Final = TenantId("fixture-authority")
TENANTS: Final = (
    (TENANT_A.value, "Fixture Tenant A", "organisation"),
    (TENANT_B.value, "Fixture Tenant B", "organisation"),
    (AUTHORITY.value, "Fixture Wildlife Authority", "authority"),
)

# Synthetic world landmarks (see data/fixtures/synthetic_habarana/build.py).
CENTRE: Final = (80.75, 8.03)  # D1/D2 edge, S1/S2/S3 corner, inside Fixture Town
ROAD_LATITUDE: Final = 8.01  # Fixture Road runs east-west along this latitude
CIRCLE_RADIUS_M: Final = 500
CORRIDOR_HALF_WIDTH_M: Final = 50
FOV_FROM: Final = datetime(2025, 1, 1, tzinfo=UTC)
# Event partitions the fixture prepares (the flood season, the months after it, the default test time).
EVENT_TEST_MONTHS: Final = (
    datetime(2025, 11, 1, tzinfo=UTC),
    datetime(2026, 3, 1, tzinfo=UTC),
    datetime(2026, 9, 1, tzinfo=UTC),
)


@dataclass(frozen=True, slots=True)
class OpsWorld:
    site_a1: uuid.UUID
    camera_a1: uuid.UUID
    camera_a1_fov: uuid.UUID
    sensor_a2: uuid.UUID
    camera_b1: uuid.UUID
    camera_b2_shared: uuid.UUID
    polygon_fence: uuid.UUID
    circle_fence: uuid.UUID
    corridor_fence: uuid.UUID
    archived_fence: uuid.UUID
    future_fence: uuid.UUID
    b_private_fence: uuid.UUID
    b_authority_fence: uuid.UUID
    b_shared_fence: uuid.UUID


def point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


def ewkt_box(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> str:
    return (
        f"SRID=4326;POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},{max_lon} {max_lat},"
        f"{min_lon} {max_lat},{min_lon} {min_lat}))"
    )


_INSERT_SITE = text(
    """
    INSERT INTO ops.site (name, external_id, site_type, geom, position_source, position_accuracy_m)
    VALUES (:name, :external_id, 'pole', public.ST_GeomFromEWKT(:ewkt), 'gps', 3)
    RETURNING id
    """
)
_INSERT_DEVICE = text(
    """
    INSERT INTO ops.device (
        name, external_id, site_id, device_type, geom, position_source, position_accuracy_m,
        sharing_policy, shared_with_tenants
    ) VALUES (
        :name, :external_id, :site_id, :device_type, public.ST_GeomFromEWKT(:ewkt), 'gps', 3,
        :sharing_policy, :shared_with
    )
    RETURNING id
    """
).bindparams(bindparam("shared_with", type_=ARRAY(Text)))
_INSERT_FOV = text(
    """
    INSERT INTO ops.device_field_of_view (
        device_id, geometry_method, bearing_deg, fov_deg, range_m, valid_during
    )
    VALUES (:device_id, 'modelled', :bearing, :fov, :range, tstzrange(:valid_from, NULL))
    RETURNING id
    """
)
_INSERT_GEOFENCE = text(
    """
    INSERT INTO ops.geofence (
        name, geofence_kind, definition_geom, radius_m, status, effective_during, sharing_policy,
        shared_with_tenants
    ) VALUES (
        :name, :kind, public.ST_GeomFromEWKT(:ewkt), :radius, :status,
        tstzrange(:effective_from, NULL), :sharing_policy, :shared_with
    )
    RETURNING id
    """
).bindparams(bindparam("shared_with", type_=ARRAY(Text)))


async def _site(session: AsyncSession, name: str, lon: float, lat: float) -> uuid.UUID:
    ewkt = f"SRID=4326;POINT({lon} {lat})"
    return uuid.UUID(
        str(
            (
                await session.execute(_INSERT_SITE, {"name": name, "external_id": name, "ewkt": ewkt})
            ).scalar_one()
        )
    )


async def _device(
    session: AsyncSession,
    name: str,
    device_type: str,
    lon: float,
    lat: float,
    *,
    site_id: uuid.UUID | None = None,
    sharing_policy: str = "private",
    shared_with: list[str] | None = None,
) -> uuid.UUID:
    result = await session.execute(
        _INSERT_DEVICE,
        {
            "name": name,
            "external_id": name,
            "site_id": site_id,
            "device_type": device_type,
            "ewkt": f"SRID=4326;POINT({lon} {lat})",
            "sharing_policy": sharing_policy,
            "shared_with": shared_with or [],
        },
    )
    return uuid.UUID(str(result.scalar_one()))


async def _geofence(
    session: AsyncSession,
    name: str,
    kind: str,
    ewkt: str,
    *,
    radius: float | None = None,
    status: str = "active",
    effective_from: datetime = FOV_FROM,
    sharing_policy: str = "private",
    shared_with: list[str] | None = None,
) -> uuid.UUID:
    result = await session.execute(
        _INSERT_GEOFENCE,
        {
            "name": name,
            "kind": kind,
            "ewkt": ewkt,
            "radius": radius,
            "status": status,
            "effective_from": effective_from,
            "sharing_policy": sharing_policy,
            "shared_with": shared_with or [],
        },
    )
    return uuid.UUID(str(result.scalar_one()))


async def build_ops_world(session_factory: async_sessionmaker[AsyncSession]) -> OpsWorld:
    centre_lon, centre_lat = CENTRE
    async with transaction(session_factory, TENANT_A) as session:
        site_a1 = await _site(session, "Fixture Site A1", 80.7450, 8.0100)
        camera_a1 = await _device(session, "Fixture Camera A1", "camera", 80.7450, 8.0100, site_id=site_a1)
        fov = await session.execute(
            _INSERT_FOV,
            {"device_id": camera_a1, "bearing": 0, "fov": 60, "range": 300, "valid_from": FOV_FROM},
        )
        camera_a1_fov = uuid.UUID(str(fov.scalar_one()))
        sensor_a2 = await _device(session, "Fixture Sensor A2", "acoustic_sensor", 80.7550, 8.0150)
        polygon_fence = await _geofence(
            session, "Fixture Polygon Fence", "polygon", ewkt_box(80.748, 8.028, 80.752, 8.032)
        )
        circle_fence = await _geofence(
            session,
            "Fixture Circle Fence",
            "circle",
            f"SRID=4326;POINT({centre_lon} {centre_lat})",
            radius=CIRCLE_RADIUS_M,
        )
        corridor_fence = await _geofence(
            session,
            "Fixture Corridor Fence",
            "corridor",
            f"SRID=4326;LINESTRING(80.70 {ROAD_LATITUDE},80.80 {ROAD_LATITUDE})",
            radius=CORRIDOR_HALF_WIDTH_M,
        )
        archived_fence = await _geofence(
            session,
            "Fixture Archived Fence",
            "polygon",
            ewkt_box(80.748, 8.028, 80.752, 8.032),
            status="archived",
        )
        future_fence = await _geofence(
            session,
            "Fixture Future Fence",
            "polygon",
            ewkt_box(80.748, 8.028, 80.752, 8.032),
            effective_from=datetime(2099, 1, 1, tzinfo=UTC),
        )

    async with transaction(session_factory, TENANT_B) as session:
        camera_b1 = await _device(session, "Fixture Camera B1", "camera", 80.7505, 8.0305)
        camera_b2_shared = await _device(
            session,
            "Fixture Camera B2",
            "camera",
            80.7510,
            8.0290,
            sharing_policy="shared",
            shared_with=[TENANT_A.value],
        )
        b_private_fence = await _geofence(
            session, "Fixture B Private Fence", "polygon", ewkt_box(80.745, 8.025, 80.755, 8.035)
        )
        b_authority_fence = await _geofence(
            session,
            "Fixture B Authority Fence",
            "polygon",
            ewkt_box(80.745, 8.025, 80.755, 8.035),
            sharing_policy="authority_only",
        )
        b_shared_fence = await _geofence(
            session,
            "Fixture B Shared Fence",
            "polygon",
            ewkt_box(80.705, 8.055, 80.715, 8.065),
            sharing_policy="shared",
            shared_with=[TENANT_A.value],
        )

    return OpsWorld(
        site_a1=site_a1,
        camera_a1=camera_a1,
        camera_a1_fov=camera_a1_fov,
        sensor_a2=sensor_a2,
        camera_b1=camera_b1,
        camera_b2_shared=camera_b2_shared,
        polygon_fence=polygon_fence,
        circle_fence=circle_fence,
        corridor_fence=corridor_fence,
        archived_fence=archived_fence,
        future_fence=future_fence,
        b_private_fence=b_private_fence,
        b_authority_fence=b_authority_fence,
        b_shared_fence=b_shared_fence,
    )
