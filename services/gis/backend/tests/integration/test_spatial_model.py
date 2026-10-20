"""Database-level behaviour of the spatial data model (migrations 0002-0005).

Constraints, triggers, functions, indexes, partitions and row-level security are exercised directly in
SQL, the way any client of the database (including tools other than this service) would meet them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pytest
from pyproj import Geod
from shapely import box
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import DEFAULT_SERVICE_AREA_BBOX
from app.core.tenancy import TenantId
from app.db.base import APPLICATION_SCHEMAS
from app.db.session import transaction
from app.spatial.crs import wgs84_to_metric_xy
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import AUTHORITY, TENANT_A, TENANT_B, ewkt_box

pytestmark = pytest.mark.usefixtures("spatial_world")

EVENT_INSERT = (
    "INSERT INTO geo.event_location (event_id, observed_at, event_type, source_type, location_source, geom) "
    "VALUES (:id, '2026-09-10T10:00:00+05:30', 'test.probe', 'sensor', 'sensor', "
    "public.ST_GeomFromEWKT(:ewkt))"
)
SPATIAL_TABLES = (
    "ref.admin_area",
    "ref.settlement",
    "ref.facility",
    "ref.road",
    "ref.water_body",
    "ref.protected_area",
    "ref.risk_zone",
    "ops.site",
    "ops.device",
    "ops.device_field_of_view",
    "ops.geofence",
    "geo.event_location",
)


async def fetch(
    world: SpatialWorld, sql: str, params: Mapping[str, Any] | None = None, *, tenant: TenantId | None = None
) -> Any:
    async with transaction(world.app_sessions, tenant) as session:
        return (await session.execute(text(sql), dict(params or {}))).one()


async def migrator_fetch(world: SpatialWorld, sql: str, params: Mapping[str, Any] | None = None) -> Any:
    async with transaction(world.migrator_sessions) as session:
        return (await session.execute(text(sql), dict(params or {}))).all()


async def expect_failure(
    world: SpatialWorld,
    sql: str,
    params: Mapping[str, Any],
    match: str,
    *,
    tenant: TenantId | None = TENANT_A,
) -> DBAPIError:
    with pytest.raises(DBAPIError, match=match) as info:
        async with transaction(world.app_sessions, tenant) as session:
            await session.execute(text(sql), dict(params))
    return info.value


# --- platform --------------------------------------------------------------------------------------------


async def test_extensions_and_uuid_v7_keys(spatial_world: SpatialWorld) -> None:
    rows = await migrator_fetch(
        spatial_world,
        "SELECT extname FROM pg_extension WHERE extname IN ('postgis', 'btree_gist') ORDER BY 1",
    )
    assert [r.extname for r in rows] == ["btree_gist", "postgis"]
    row = await fetch(spatial_world, "SELECT uuid_extract_version(id) AS version FROM ref.road LIMIT 1")
    assert row.version == 7


async def test_database_service_envelope_matches_application_default(spatial_world: SpatialWorld) -> None:
    row = await fetch(
        spatial_world,
        "SELECT public.ST_XMin(b) AS x1, public.ST_YMin(b) AS y1, "
        "public.ST_XMax(b) AS x2, public.ST_YMax(b) AS y2 "
        "FROM (SELECT meta.sri_lanka_bounds()::public.box3d AS b) AS s",
    )
    assert (row.x1, row.y1, row.x2, row.y2) == pytest.approx(DEFAULT_SERVICE_AREA_BBOX, abs=1e-6)


@pytest.mark.parametrize(
    ("lon", "lat", "inside"),
    [
        (79.857751, 6.931966, True),  # Colombo
        (80.005028, 9.675002, True),  # Jaffna
        (80.5895, 5.9235, True),  # Dondra Head
        (79.44, 5.66, True),  # envelope corner (inclusive)
        (82.15, 10.08, True),  # opposite corner
        (79.4399999, 7.0, False),  # just west of the envelope
        (6.931966, 79.857751, False),  # Colombo with the axes swapped
        (80.27, 13.08, False),  # Chennai
        (73.51, 4.17, False),  # Malé
        (0.0, 0.0, False),
    ],
)
async def test_service_envelope_check(
    spatial_world: SpatialWorld, lon: float, lat: float, inside: bool
) -> None:
    row = await fetch(
        spatial_world,
        "SELECT meta.is_within_sri_lanka(public.ST_SetSRID(public.ST_MakePoint(:lon, :lat), 4326)) AS inside",
        {"lon": lon, "lat": lat},
    )
    assert row.inside is inside


async def test_envelope_check_requires_wgs84(spatial_world: SpatialWorld) -> None:
    row = await fetch(
        spatial_world,
        "SELECT meta.is_within_sri_lanka(public.ST_SetSRID(public.ST_MakePoint(80, 7), 5235)) AS ok",
    )
    assert row.ok is False


# --- geometry constraints --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ewkt", "constraint"),
    [
        ("SRID=4326;POINT(8.03 80.75)", "ck_event_location_geom_in_service_area"),  # swapped lat/lon
        ("SRID=4326;POINT(80.27 13.08)", "ck_event_location_geom_in_service_area"),  # Chennai
        (
            "SRID=4326;POLYGON((80.7 8.0,80.8 8.1,80.8 8.0,80.7 8.1,80.7 8.0))",
            "ck_event_location_geom_valid",
        ),  # bow-tie
        ("SRID=4326;POINT EMPTY", "ck_event_location_geom_not_empty"),
        ("SRID=4326;GEOMETRYCOLLECTION(POINT(80.75 8.03))", "ck_event_location_geometry_type"),
    ],
)
async def test_event_geometry_constraints(spatial_world: SpatialWorld, ewkt: str, constraint: str) -> None:
    await expect_failure(spatial_world, EVENT_INSERT, {"id": "evt-bad", "ewkt": ewkt}, constraint)


async def test_geometries_in_another_crs_are_rejected(spatial_world: SpatialWorld) -> None:
    await expect_failure(
        spatial_world, EVENT_INSERT, {"id": "evt-crs", "ewkt": "SRID=5235;POINT(500000 500000)"}, "SRID"
    )


async def test_invalid_reference_polygon_is_repaired_and_logged(spatial_world: SpatialWorld) -> None:
    rows = await migrator_fetch(
        spatial_world,
        """
        SELECT r.table_name, r.reason, r.repaired_area_m2, p.name,
               public.ST_IsValid(p.geom) AS valid, public.ST_NumGeometries(p.geom) AS parts,
               public.ST_Area(p.geom_metric) AS area
        FROM meta.geometry_repair AS r JOIN ref.protected_area AS p ON p.id = r.feature_id
        """,
    )
    assert len(rows) == 1
    repair = rows[0]
    assert (repair.table_name, repair.name, repair.valid, repair.parts) == (
        "protected_area",
        "Fixture Bow-tie Reserve",
        True,
        2,
    )
    assert repair.reason.startswith("Self-intersection")
    assert repair.repaired_area_m2 == pytest.approx(repair.area, rel=1e-9)


async def test_unrepairable_reference_polygon_is_rejected(spatial_world: SpatialWorld) -> None:
    collapsed = "SRID=4326;MULTIPOLYGON(((80.71 8.01,80.72 8.02,80.71 8.01,80.71 8.01)))"

    async def insert_collapsed_zone() -> None:
        async with transaction(spatial_world.migrator_sessions) as session:
            release_id = await session.scalar(
                text("INSERT INTO meta.ref_data_release (code) VALUES ('ref-2026.09-collapse') RETURNING id")
            )
            load_id = await session.scalar(
                text(
                    """
                    INSERT INTO meta.dataset_load (release_id, layer_id, source_id, source_file,
                        source_checksum_sha256, source_crs, transformation, loader_version, source_reference,
                        licence, attribution, commercial_use_allowed, redistribution_allowed, share_alike,
                        licence_review_status)
                    SELECT :release, l.id, s.id, 'collapsed.geojson', repeat('0', 64), 'EPSG:4326',
                           'none', 'test', 'test', s.licence, s.attribution, s.commercial_use_allowed,
                           s.redistribution_allowed, s.share_alike, s.licence_review_status
                    FROM meta.layer l, meta.data_source s
                    WHERE l.code = 'ref.risk_zone' AND s.code = 'gis-core-fixtures'
                    RETURNING id
                    """
                ),
                {"release": release_id},
            )
            await session.execute(
                text(
                    "INSERT INTO ref.risk_zone (release_id, load_id, name, risk_type, severity, geom) "
                    "VALUES (:release, :load, 'Collapsed', 'flood', 1, public.ST_GeomFromEWKT(:ewkt))"
                ),
                {"release": release_id, "load": load_id, "ewkt": collapsed},
            )

    with pytest.raises(DBAPIError, match="cannot be repaired"):
        await insert_collapsed_zone()


async def test_generated_metric_columns_use_epsg_5235(spatial_world: SpatialWorld) -> None:
    rows = await migrator_fetch(
        spatial_world,
        """
        SELECT f_table_schema || '.' || f_table_name AS tbl, f_geometry_column AS col, srid
        FROM public.geometry_columns
        WHERE f_table_schema IN ('ref', 'ops', 'geo', 'meta') AND f_table_name NOT LIKE '%\\_p______'
        """,
    )
    columns = {(r.tbl, r.col): r.srid for r in rows}
    for table in SPATIAL_TABLES:
        assert columns[(table, "geom")] == 4326, table
        assert columns[(table, "geom_metric")] == 5235, table
    assert columns[("ref.area_part", "geom")] == 4326


async def test_wgs84_to_sld99_agrees_between_database_and_application(spatial_world: SpatialWorld) -> None:
    rows = await migrator_fetch(
        spatial_world,
        "SELECT public.ST_X(geom) AS lon, public.ST_Y(geom) AS lat, "
        "public.ST_X(geom_metric) AS e, public.ST_Y(geom_metric) AS n, "
        "public.ST_Distance(public.ST_Transform(geom_metric, 4326)::public.geography, "
        "geom::public.geography) "
        "AS round_trip_m "
        "FROM ref.settlement WHERE public.GeometryType(geom) = 'POINT'",
    )
    assert len(rows) >= 14
    for row in rows:
        easting, northing = wgs84_to_metric_xy(row.lon, row.lat)
        assert math.hypot(easting - row.e, northing - row.n) < 0.005
        assert row.round_trip_m < 0.005
        # SLD99 grid coordinates of Sri Lanka lie roughly within 330-700 km E and 360-820 km N.
        assert 300_000 < row.e < 720_000
        assert 350_000 < row.n < 830_000


async def test_grid_distance_matches_geodesic_distance(spatial_world: SpatialWorld) -> None:
    row = await fetch(
        spatial_world,
        """
        SELECT public.ST_Distance(a.geom_metric, b.geom_metric) AS grid_m,
               public.ST_X(a.geom) AS ax, public.ST_Y(a.geom) AS ay,
               public.ST_X(b.geom) AS bx, public.ST_Y(b.geom) AS by
        FROM ref.settlement a, ref.settlement b
        WHERE a.name = 'Jaffna' AND b.name = 'Matara'
        """,
    )
    geodesic = Geod(ellps="WGS84").inv(row.ax, row.ay, row.bx, row.by)[2]
    assert row.grid_m == pytest.approx(geodesic, rel=5e-4)  # ~410 km, scale error < 0.05 %


async def test_distance_threshold_is_inclusive(spatial_world: SpatialWorld) -> None:
    exact = await fetch(
        spatial_world,
        "SELECT public.ST_DWithin(public.ST_Point(500000, 500000, 5235), "
        "public.ST_Point(500300, 500400, 5235), 500) "
        "AS at_500, public.ST_DWithin(public.ST_Point(500000, 500000, 5235), "
        "public.ST_Point(500300, 500400, 5235), 499.999999) AS below",
    )
    assert (exact.at_500, exact.below) == (True, False)
    stored = await fetch(
        spatial_world,
        """
        WITH pair AS (
            SELECT a.geom_metric AS a, b.geom_metric AS b,
                   public.ST_Distance(a.geom_metric, b.geom_metric) AS d
            FROM ops.device a, ops.site b WHERE a.name = 'Fixture Sensor A2' AND b.name = 'Fixture Site A1'
        )
        SELECT d, public.ST_DWithin(a, b, d) AS at_d, public.ST_DWithin(a, b, d - 1e-6) AS below FROM pair
        """,
        tenant=TENANT_A,
    )
    assert stored.d > 0
    assert (stored.at_d, stored.below) == (True, False)


@pytest.mark.parametrize(
    ("lon", "lat", "codes"),
    [
        (80.71, 8.00, ["SYN-P1", "SYN-D1", "SYN-S1", "SYN-G1"]),  # inside
        (80.60, 7.90, []),  # outside
        (80.75, 8.03, ["SYN-P1", "SYN-D1", "SYN-D2", "SYN-S1", "SYN-S2", "SYN-S3", "SYN-G2"]),  # boundary
        (80.80, 8.08, ["SYN-P1", "SYN-D2", "SYN-S3"]),  # outer corner vertex
    ],
)
async def test_point_in_polygon_through_area_parts(
    spatial_world: SpatialWorld, lon: float, lat: float, codes: list[str]
) -> None:
    rows = await migrator_fetch(
        spatial_world,
        """
        SELECT DISTINCT a.level, a.code
        FROM ref.area_part p JOIN ref.admin_area a ON a.id = p.feature_id
        WHERE p.release_id = :release AND p.area_kind = 'admin_area'
          AND public.ST_Intersects(p.geom, public.ST_SetSRID(public.ST_MakePoint(:lon, :lat), 4326))
        ORDER BY a.level, a.code
        """,
        {"release": spatial_world.synthetic.release_id, "lon": lon, "lat": lat},
    )
    assert [r.code for r in rows] == codes


async def test_area_parts_cover_their_features_exactly(spatial_world: SpatialWorld) -> None:
    rows = await migrator_fetch(
        spatial_world,
        """
        SELECT a.code, public.ST_Area(a.geom) AS whole, public.ST_Area(public.ST_Union(p.geom)) AS parts,
               max(public.ST_NPoints(p.geom)) AS max_points, count(*) AS n
        FROM ref.admin_area a JOIN ref.area_part p ON p.feature_id = a.id
        GROUP BY a.id
        """,
    )
    assert len(rows) == 79 + 8  # open data + synthetic admin areas
    for row in rows:
        assert row.parts == pytest.approx(row.whole, rel=1e-9), row.code
        assert row.max_points <= 256
    assert max(r.n for r in rows) > 1, "large areas are subdivided"


# --- field of view and geofences ---------------------------------------------------------------------------


async def test_modelled_field_of_view_sector(spatial_world: SpatialWorld) -> None:
    row = await fetch(
        spatial_world,
        """
        SELECT public.ST_Area(f.geom_metric) AS area,
               public.ST_Y(public.ST_Centroid(f.geom_metric)) - public.ST_Y(d.geom_metric) AS north,
               abs(public.ST_X(public.ST_Centroid(f.geom_metric)) - public.ST_X(d.geom_metric)) AS east,
               public.ST_Covers(f.geom, d.geom) AS covers_device
        FROM ops.device_field_of_view f JOIN ops.device d ON d.id = f.device_id
        WHERE d.name = 'Fixture Camera A1'
        """,
        tenant=TENANT_A,
    )
    assert row.area == pytest.approx(math.pi * 300**2 * 60 / 360, rel=5e-3)
    assert row.north > 150
    assert row.east < 0.01  # bearing 0: the sector points north
    assert row.covers_device is True


async def test_field_of_view_periods_cannot_overlap(spatial_world: SpatialWorld) -> None:
    await expect_failure(
        spatial_world,
        "INSERT INTO ops.device_field_of_view (device_id, geometry_method, bearing_deg, fov_deg, range_m, "
        "valid_during) VALUES (:device, 'modelled', 90, 45, 100, tstzrange('2026-01-01', NULL))",
        {"device": spatial_world.ops.camera_a1},
        "ex_device_field_of_view_device_id_valid_during",
    )


async def test_moving_a_device_moves_its_current_field_of_view(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        await session.execute(
            text("UPDATE ops.device SET geom = public.ST_Translate(geom, 0.001, 0) WHERE id = :id"),
            {"id": spatial_world.ops.camera_a1},
        )
        row = (
            await session.execute(
                text(
                    "SELECT public.ST_Covers(f.geom, d.geom) AS covers, f.version, "
                    "d.version AS device_version "
                    "FROM ops.device_field_of_view f JOIN ops.device d ON d.id = f.device_id WHERE d.id = :id"
                ),
                {"id": spatial_world.ops.camera_a1},
            )
        ).one()
        assert (row.covers, row.version, row.device_version) == (True, 2, 2)
        await session.rollback()


async def test_closed_field_of_view_keeps_its_sector(spatial_world: SpatialWorld) -> None:
    fov_id, device_id = spatial_world.ops.camera_a1_fov, spatial_world.ops.camera_a1
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        before = await session.scalar(
            text("SELECT public.ST_AsEWKB(geom) FROM ops.device_field_of_view WHERE id = :id"), {"id": fov_id}
        )
        await session.execute(
            text(
                "UPDATE ops.device_field_of_view SET valid_during = tstzrange(lower(valid_during), now()) "
                "WHERE id = :id"
            ),
            {"id": fov_id},
        )
        await session.execute(
            text("UPDATE ops.device SET geom = public.ST_Translate(geom, 0.002, 0) WHERE id = :id"),
            {"id": device_id},
        )
        await session.execute(
            text('UPDATE ops.device_field_of_view SET attributes = \'{"note": "closed"}\' WHERE id = :id'),
            {"id": fov_id},
        )
        after = await session.scalar(
            text("SELECT public.ST_AsEWKB(geom) FROM ops.device_field_of_view WHERE id = :id"), {"id": fov_id}
        )
        await session.rollback()
    assert after == before


async def test_surveyed_field_of_view_is_stored_as_supplied(spatial_world: SpatialWorld) -> None:
    surveyed = ewkt_box(80.744, 8.010, 80.746, 8.012)
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        row = (
            await session.execute(
                text(
                    "INSERT INTO ops.device_field_of_view (device_id, geometry_method, geom, valid_during) "
                    "VALUES (:device, 'surveyed', public.ST_GeomFromEWKT(:ewkt), "
                    "tstzrange('2020-01-01', '2021-01-01')) "
                    "RETURNING public.GeometryType(geom) AS kind, "
                    "public.ST_Equals(geom, public.ST_GeomFromEWKT(:ewkt)) AS same"
                ),
                {"device": spatial_world.ops.camera_a1, "ewkt": surveyed},
            )
        ).one()
        await session.rollback()
    assert (row.kind, row.same) == ("MULTIPOLYGON", True)
    await expect_failure(
        spatial_world,
        "INSERT INTO ops.device_field_of_view (device_id, geometry_method, geom, valid_during) "
        "VALUES (:device, 'surveyed', public.ST_GeomFromEWKT(:ewkt), tstzrange('2020-01-01', '2021-01-01'))",
        {
            "device": spatial_world.ops.camera_a1,
            "ewkt": "SRID=4326;POLYGON((80.7 8.0,80.8 8.1,80.8 8.0,80.7 8.1,80.7 8.0))",
        },
        "invalid field-of-view polygon",
    )


@pytest.mark.parametrize(
    ("kind", "ewkt", "radius", "message"),
    [
        (
            "polygon",
            "SRID=4326;POLYGON((80.7 8.0,80.8 8.1,80.8 8.0,80.7 8.1,80.7 8.0))",
            None,
            "Self-intersection",
        ),
        ("circle", "SRID=4326;POINT(8.03 80.75)", 100, "outside the service area"),
        ("circle", "SRID=4326;POINT(80.75 8.03)", None, "cannot be defined"),
        ("corridor", "SRID=4326;POINT(80.75 8.03)", 50, "cannot be defined"),
        ("polygon", "SRID=4326;POLYGON EMPTY", None, "empty"),
    ],
)
async def test_invalid_geofences_are_rejected(
    spatial_world: SpatialWorld, kind: str, ewkt: str, radius: float | None, message: str
) -> None:
    error = await expect_failure(
        spatial_world,
        "INSERT INTO ops.geofence (name, geofence_kind, definition_geom, radius_m) "
        "VALUES ('bad', :kind, public.ST_GeomFromEWKT(:ewkt), :radius)",
        {"kind": kind, "ewkt": ewkt, "radius": radius},
        message,
    )
    assert getattr(error.orig, "sqlstate", None) in {"22023", "23514"}


async def test_circle_geofence_derived_geometry(spatial_world: SpatialWorld) -> None:
    row = await fetch(
        spatial_world,
        """
        SELECT area_m2, public.ST_Area(geom_metric) AS search_area, version,
               public.ST_Covers(geom_metric, public.ST_Buffer(definition_geom_metric, radius_m - 0.001, 256))
                   AS covers_circle,
               public.ST_HausdorffDistance(public.ST_Boundary(geom_metric),
                   public.ST_Boundary(public.ST_Buffer(definition_geom_metric, radius_m, 256))) AS gap_m
        FROM ops.geofence WHERE id = :id
        """,
        {"id": spatial_world.ops.circle_fence},
        tenant=TENANT_A,
    )
    assert row.area_m2 == pytest.approx(math.pi * 500**2)
    assert row.covers_circle is True
    assert row.gap_m < 0.2
    assert row.search_area > row.area_m2


async def test_geofence_update_recomputes_geometry_and_version(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        row = (
            await session.execute(
                text(
                    "UPDATE ops.geofence SET definition_geom = public.ST_GeomFromEWKT(:ewkt) "
                    "WHERE id = :id RETURNING version, round(area_m2) AS area"
                ),
                {"id": spatial_world.ops.polygon_fence, "ewkt": ewkt_box(80.74, 8.02, 80.76, 8.04)},
            )
        ).one()
        await session.rollback()
    expected = Geod(ellps="WGS84").geometry_area_perimeter(box(80.74, 8.02, 80.76, 8.04))[0]
    assert row.version == 2
    assert row.area == pytest.approx(abs(expected), rel=5e-4)


# --- tenancy ---------------------------------------------------------------------------------------------


async def test_row_level_security_per_tenant(spatial_world: SpatialWorld) -> None:
    sql = (
        "SELECT (SELECT count(*) FROM ops.device) AS devices, (SELECT count(*) FROM ops.geofence) AS fences, "
        "(SELECT count(*) FROM ops.device_field_of_view) AS fovs, (SELECT count(*) FROM ops.site) AS sites"
    )
    a = await fetch(spatial_world, sql, tenant=TENANT_A)
    b = await fetch(spatial_world, sql, tenant=TENANT_B)
    authority = await fetch(spatial_world, sql, tenant=AUTHORITY)
    nobody = await fetch(spatial_world, sql)
    assert tuple(a) == (3, 6, 1, 1)  # own devices and fences + B's shared camera and shared fence
    assert tuple(b) == (2, 3, 0, 0)
    assert tuple(authority) == (1, 2, 0, 0)  # B's shared camera; B's shared and authority-only fences
    assert tuple(nobody) == (0, 0, 0, 0)


async def test_tenants_cannot_write_for_others(spatial_world: SpatialWorld) -> None:
    await expect_failure(
        spatial_world,
        "INSERT INTO ops.site (tenant_id, name, geom, position_source) "
        "VALUES ('fixture-tenant-b', 'x', public.ST_GeomFromEWKT('SRID=4326;POINT(80.75 8.03)'), 'gps')",
        {},
        "row-level security",
    )
    async with transaction(spatial_world.app_sessions, TENANT_B) as session:
        changed = await session.execute(
            text("UPDATE ops.device SET name = 'hijacked' WHERE id = :id RETURNING id"),
            {"id": spatial_world.ops.camera_a1},
        )
        assert changed.all() == []


async def test_related_rows_must_belong_to_the_same_tenant(spatial_world: SpatialWorld) -> None:
    await expect_failure(
        spatial_world,
        "INSERT INTO ops.device (site_id, name, device_type, geom, position_source) "
        "VALUES (:site, 'x', 'camera', public.ST_GeomFromEWKT('SRID=4326;POINT(80.75 8.03)'), 'gps')",
        {"site": spatial_world.ops.site_a1},
        "fk_device_site_id_tenant_id_site",
        tenant=TENANT_B,
    )


async def test_event_partitions_are_not_directly_readable(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        await session.execute(
            text(EVENT_INSERT), {"id": "evt-partition", "ewkt": "SRID=4326;POINT(80.75 8.03)"}
        )
        via_parent = await session.scalar(
            text("SELECT count(*) FROM geo.event_location WHERE event_id = 'evt-partition'")
        )
        direct = await session.scalar(
            text("SELECT count(*) FROM geo.event_location_p202609 WHERE event_id = 'evt-partition'")
        )
        await session.rollback()
    assert (via_parent, direct) == (1, 0)


async def test_on_demand_partitions_are_idempotent_and_bounded(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.app_sessions) as session:
        first = await session.scalar(text("SELECT geo.ensure_event_partition(now())"))
        again = await session.scalar(text("SELECT geo.ensure_event_partition(now())"))
    assert first == again
    for moment in ("2010-06-01T00:00:00Z", "infinity", "2099-01-01T00:00:00Z"):
        with pytest.raises(DBAPIError, match="observed_at"):
            async with transaction(spatial_world.app_sessions) as session:
                await session.execute(
                    text("SELECT geo.ensure_event_partition(CAST(CAST(:t AS text) AS timestamptz))"),
                    {"t": moment},
                )


@pytest.mark.parametrize(
    "function", ["create_event_partitions(now())", "prepare_event_partitions(now(), now())"]
)
async def test_runtime_login_cannot_prepare_arbitrary_months(
    spatial_world: SpatialWorld, function: str
) -> None:
    await expect_failure(spatial_world, f"SELECT geo.{function}", {}, "permission denied")


async def test_operators_prepare_months_in_utc(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        # 23:30 at UTC-1 on 31 May is 00:30 UTC on 1 June.
        june = await session.scalar(
            text("SELECT geo.create_event_partitions(CAST(CAST(:t AS text) AS timestamptz))"),
            {"t": "2010-05-31T23:30:00-01:00"},
        )
        months = (
            (
                await session.execute(
                    text(
                        "SELECT geo.prepare_event_partitions("
                        "'2010-04-15'::timestamptz, '2010-06-01'::timestamptz)"
                    )
                )
            )
            .scalars()
            .all()
        )
        with pytest.raises(DBAPIError, match="13 months ahead"):
            async with session.begin_nested():
                await session.execute(text("SELECT geo.create_event_partitions(now() + interval '2 years')"))
        await session.rollback()
    assert june == "201006"
    assert months == ["201004", "201005", "201006"]


async def test_events_cannot_be_observed_after_they_are_received(spatial_world: SpatialWorld) -> None:
    await expect_failure(
        spatial_world,
        "INSERT INTO geo.event_location (event_id, observed_at, received_at, event_type, source_type, "
        "location_source, geom) VALUES ('evt-future', '2026-09-10T10:00:00Z', '2026-09-08T10:00:00Z', "
        "'test.probe', 'sensor', 'sensor', public.ST_GeomFromEWKT('SRID=4326;POINT(80.75 8.03)'))",
        {},
        "ck_event_location_observed_at_not_future",
    )


async def test_events_without_a_partition_fail_loudly(spatial_world: SpatialWorld) -> None:
    await expect_failure(
        spatial_world,
        EVENT_INSERT.replace("'2026-09-10T10:00:00+05:30'", "'2011-01-15T00:00:00Z'"),
        {"id": "evt-no-partition", "ewkt": "SRID=4326;POINT(80.75 8.03)"},
        "no partition",
    )


# --- releases, lineage, licences ---------------------------------------------------------------------------


async def test_published_release_is_immutable(spatial_world: SpatialWorld) -> None:
    for sql in (
        "UPDATE ref.road SET name = 'renamed' WHERE release_id = :release",
        "DELETE FROM ref.road WHERE release_id = :release",
        "DELETE FROM meta.ref_data_release WHERE id = :release",
        "UPDATE meta.ref_data_release SET status = 'draft' WHERE id = :release",
    ):
        with pytest.raises(DBAPIError, match=r"published|cannot move"):
            async with transaction(spatial_world.migrator_sessions) as session:
                await session.execute(text(sql), {"release": spatial_world.open_data.release_id})


async def test_runtime_login_cannot_change_reference_data(spatial_world: SpatialWorld) -> None:
    await expect_failure(spatial_world, "DELETE FROM ref.road", {}, "permission denied")
    await expect_failure(spatial_world, "UPDATE meta.layer SET name = 'x'", {}, "permission denied")


async def test_retiring_and_purging_a_release(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        release = spatial_world.synthetic.release_id
        await session.execute(
            text("UPDATE meta.ref_data_release SET status = 'retired' WHERE id = :id"), {"id": release}
        )
        with pytest.raises(DBAPIError, match="retired"):
            async with session.begin_nested():
                await session.execute(
                    text("UPDATE ref.road SET name = 'x' WHERE release_id = :id"), {"id": release}
                )
        await session.execute(text("DELETE FROM meta.ref_data_release WHERE id = :id"), {"id": release})
        remaining = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM ref.admin_area WHERE release_id = :id) AS areas, "
                    "(SELECT count(*) FROM ref.area_part WHERE release_id = :id) AS parts, "
                    "(SELECT count(*) FROM meta.dataset_load WHERE release_id = :id) AS loads, "
                    "(SELECT count(*) FROM meta.geometry_repair) AS repairs"
                ),
                {"id": release},
            )
        ).one()
        await session.rollback()
    assert tuple(remaining) == (0, 0, 0, 0)


async def test_only_one_current_release(spatial_world: SpatialWorld) -> None:
    with pytest.raises(DBAPIError, match="uq_ref_data_release_is_current"):
        async with transaction(spatial_world.migrator_sessions) as session:
            await session.execute(
                text("UPDATE meta.ref_data_release SET is_current = true WHERE id = :id"),
                {"id": spatial_world.synthetic.release_id},
            )


async def test_non_commercial_sources_need_a_recorded_permission(spatial_world: SpatialWorld) -> None:
    insert = (
        "INSERT INTO meta.data_source (code, name, publisher, licence, attribution, commercial_use_allowed, "
        "redistribution_allowed, permission_reference) VALUES ('wdpa', 'World Database on Protected Areas', "
        "'UNEP-WCMC', 'WDPA-terms', 'UNEP-WCMC and IUCN, Protected Planet', false, false, :permission)"
    )
    with pytest.raises(DBAPIError, match="ck_data_source_commercial_use_permitted"):
        async with transaction(spatial_world.migrator_sessions) as session:
            await session.execute(text(insert), {"permission": None})
    async with transaction(spatial_world.migrator_sessions) as session:
        await session.execute(text(insert), {"permission": "UNEP-WCMC licence 2026-001"})
        await session.rollback()


# --- registry, indexes, scope ----------------------------------------------------------------------------


async def test_layer_registry_describes_every_spatial_table(spatial_world: SpatialWorld) -> None:
    rows = await migrator_fetch(
        spatial_world,
        "SELECT code, layer_group, tenant_scoped, to_regclass(code) IS NOT NULL AS exists FROM meta.layer",
    )
    assert {r.code for r in rows} == set(SPATIAL_TABLES)
    assert all(r.exists for r in rows)
    groups = {r.code: (r.layer_group, r.tenant_scoped) for r in rows}
    assert groups["ref.road"] == ("reference", False)
    assert groups["ops.geofence"] == ("operational", True)
    assert groups["geo.event_location"] == ("event", True)


async def test_spatial_and_temporal_indexes_exist(spatial_world: SpatialWorld) -> None:
    rows = await migrator_fetch(
        spatial_world,
        """
        SELECT n.nspname || '.' || t.relname AS tbl, am.amname AS method,
               array_agg(a.attname::text ORDER BY k.ord) AS columns
        FROM pg_index i
        JOIN pg_class ic ON ic.oid = i.indexrelid
        JOIN pg_am am ON am.oid = ic.relam
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        CROSS JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
        WHERE n.nspname IN ('ref', 'ops', 'geo', 'meta') AND t.relname !~ '_p[0-9]{6}$'
        GROUP BY 1, 2, ic.oid
        """,
    )
    indexes = {(r.tbl, r.method, tuple(r.columns)) for r in rows}

    def spatial(table: str, column: str) -> bool:
        return any(t == table and m == "gist" and cols[-1] == column for t, m, cols in indexes)

    for table in SPATIAL_TABLES:
        assert spatial(table, "geom"), f"{table}.geom has no GiST index"
        assert spatial(table, "geom_metric"), f"{table}.geom_metric has no GiST index"
    assert spatial("ref.area_part", "geom")
    assert spatial("ops.geofence", "definition_geom") is False  # searched through geom/geom_metric
    assert ("geo.event_location", "brin", ("observed_at",)) in indexes
    assert ("geo.event_location", "btree", ("tenant_id", "observed_at")) in indexes
    assert spatial("ref.risk_zone", "valid_during")
    assert spatial("ops.geofence", "effective_during")
    assert spatial("ops.device_field_of_view", "valid_during")  # the exclusion constraint's index


async def test_point_lookup_uses_the_spatial_index(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            (
                await session.execute(
                    text(
                        "EXPLAIN SELECT feature_id FROM ref.area_part WHERE release_id = :r "
                        "AND area_kind = 'admin_area' "
                        "AND public.ST_Intersects(geom, "
                        "public.ST_SetSRID(public.ST_MakePoint(80.75, 8.03), 4326))"
                    ),
                    {"r": spatial_world.synthetic.release_id},
                )
            ).scalars()
        )
    assert "ix_area_part_release_id_area_kind_geom_gist" in plan


async def test_no_alerting_or_notification_objects_exist(spatial_world: SpatialWorld) -> None:
    """Scope guard (ADR-0012): the GIS service stores no recipients, notification locations or alerts."""
    rows = await migrator_fetch(
        spatial_world,
        """
        SELECT n.nspname || '.' || c.relname AS name
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ANY(:schemas)
          AND c.relname ~* '(alert|notif|recipient|subscriber|subscription|contact)'
        UNION ALL
        SELECT table_schema || '.' || table_name || '.' || column_name FROM information_schema.columns
        WHERE table_schema = ANY(:schemas)
          AND column_name ~* '(alert|notif|recipient|phone|email|push_token|whatsapp)'
        """,
        {"schemas": list(APPLICATION_SCHEMAS)},
    )
    assert rows == []
