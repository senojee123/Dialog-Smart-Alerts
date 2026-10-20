"""Migration behaviour against a real PostGIS database."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.db.base import APPLICATION_SCHEMAS
from app.schemas.geo_context import GeoContext
from app.services.migrations import load_migration_heads
from tests.integration.conftest import run_alembic

SCHEMA_QUERY = text(
    "SELECT nspname, pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname = ANY(:names)"
)


async def _schemas(engine: AsyncEngine) -> dict[str, str]:
    async with engine.connect() as connection:
        rows = await connection.execute(SCHEMA_QUERY, {"names": list(APPLICATION_SCHEMAS)})
        return {row.nspname: row.owner for row in rows}


async def test_head_creates_owned_schemas_and_records_revision(
    migrated_database: Settings, migrator_engine: AsyncEngine
) -> None:
    schemas = await _schemas(migrator_engine)
    assert set(schemas) == set(APPLICATION_SCHEMAS)
    assert set(schemas.values()) == {migrated_database.db_migrator_user}
    async with migrator_engine.connect() as connection:
        applied = (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    assert frozenset(applied) == load_migration_heads(migrated_database.alembic_config_path)


@pytest.mark.parametrize(
    ("schema", "allowed", "denied"),
    [
        ("ref", {"SELECT"}, {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}),
        ("meta", {"SELECT"}, {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}),
        ("ops", {"SELECT", "INSERT", "UPDATE", "DELETE"}, {"TRUNCATE"}),
        ("geo", {"SELECT", "INSERT", "UPDATE", "DELETE"}, {"TRUNCATE"}),
        ("audit", {"SELECT", "INSERT"}, {"UPDATE", "DELETE", "TRUNCATE"}),
    ],
)
async def test_future_tables_get_least_privilege_runtime_grants(
    migrated_database: Settings,
    migrator_engine: AsyncEngine,
    schema: str,
    allowed: set[str],
    denied: set[str],
) -> None:
    """Default privileges: a table created by a later migration is usable by the runtime login as intended."""
    role = migrated_database.db_app_user
    async with migrator_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            # schema comes from the fixed parametrisation above, never from input.
            await connection.execute(
                text(f"CREATE TABLE {schema}.privilege_probe (id bigserial PRIMARY KEY)")
            )
            for privilege, expected in [(p, True) for p in allowed] + [(p, False) for p in denied]:
                granted = (
                    await connection.execute(
                        text("SELECT has_table_privilege(:role, :table, :privilege)"),
                        {"role": role, "table": f"{schema}.privilege_probe", "privilege": privilege},
                    )
                ).scalar_one()
                assert granted is expected, f"{privilege} on {schema} should be {expected}"
        finally:
            await transaction.rollback()


async def test_runtime_login_cannot_create_objects(
    migrated_database: Settings, app_engine: AsyncEngine
) -> None:
    async with app_engine.connect() as connection:
        for schema in (*APPLICATION_SCHEMAS, "public"):
            can_create = (
                await connection.execute(
                    text("SELECT has_schema_privilege(current_user, :schema, 'CREATE')"), {"schema": schema}
                )
            ).scalar_one()
            assert can_create is False, f"runtime login must not have CREATE on {schema}"
        flags = (
            await connection.execute(
                text(
                    "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
        assert not any(flags)


async def test_downgrade_and_upgrade_round_trip(
    migrated_database: Settings, migrator_engine: AsyncEngine
) -> None:
    await run_alembic(migrated_database, "downgrade", "base")
    assert await _schemas(migrator_engine) == {}
    async with migrator_engine.connect() as connection:
        postgis = (
            await connection.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'"))
        ).scalar_one_or_none()
    assert postgis is not None, "downgrade must leave the shared PostGIS extension in place"

    await run_alembic(migrated_database, "upgrade", "head")
    assert set(await _schemas(migrator_engine)) == set(APPLICATION_SCHEMAS)


async def test_downgrade_refuses_to_drop_schemas_holding_data(
    migrated_database: Settings, migrator_engine: AsyncEngine
) -> None:
    async with migrator_engine.begin() as connection:
        await connection.execute(text("CREATE TABLE ops.keep_me (id integer)"))
    try:
        with pytest.raises(Exception, match=r"keep_me|depend"):
            await run_alembic(migrated_database, "downgrade", "base")
        assert set(await _schemas(migrator_engine)) == set(APPLICATION_SCHEMAS)
    finally:
        async with migrator_engine.begin() as connection:
            await connection.execute(text("DROP TABLE ops.keep_me"))


# --- revision 20260917_0006: geo-context document layout ----------------------------------------------------

PREVIOUS_REVISION = "20260915_0005"
MIGRATION_TENANT = "migration-tenant"
MIGRATION_RELEASE = "ref-2026.09-migrate"


def _previous_document(release_id: str, observed: str) -> dict[str, Any]:
    """A document exactly as revision 0005 and the service of that time stored it."""
    return {
        "schemaVersion": "geo-context/1",
        "eventId": "evt-migrate-1",
        "observedAt": observed,
        "locationSource": "sensor",
        "geometryKind": "point",
        "referenceDataRelease": {"id": release_id, "code": MIGRATION_RELEASE},
        "computedAt": observed,
        "admin": {
            "province": {
                "id": "0192f1a0-0000-7000-8000-000000000001",
                "code": "P1",
                "name": "Province",
                "nameSi": None,
                "nameTa": None,
                "level": 1,
                "levelName": "province",
            },
            "district": None,
            "dsDivision": None,
            "gnDivision": None,
            "onBoundary": False,
        },
        "nearestSettlement": {
            "id": "0192f1a0-0000-7000-8000-000000000002",
            "name": "Town",
            "nameSi": None,
            "nameTa": None,
            "settlementType": "town",
            "geometryBasis": "footprint",
            "distanceM": 12.5,
        },
        "nearestRoad": None,
        "zones": [
            {
                "kind": "risk_zone",
                "id": "0192f1a0-0000-7000-8000-000000000003",
                "name": "Zone",
                "category": "flood",
                "severity": 3,
                "relation": "within",
            }
        ],
        "geofenceHits": [
            {
                "id": "0192f1a0-0000-7000-8000-000000000004",
                "name": "Fence",
                "geofenceKind": "circle",
                "ownerTenantId": MIGRATION_TENANT,
                "version": 2,
                "relation": "intersects",
            }
        ],
        "nearestDevices": [
            {
                "id": "0192f1a0-0000-7000-8000-000000000005",
                "name": "Camera",
                "deviceType": "camera",
                "ownerTenantId": MIGRATION_TENANT,
                "distanceM": 5.25,
            }
        ],
        "search": {
            "settlementRadiusM": 25000.0,
            "roadRadiusM": 10000.0,
            "deviceRadiusM": 5000.0,
            "deviceLimit": 5,
        },
    }


async def test_document_layout_revision_converts_stored_documents_both_ways(
    migrated_database: Settings, migrator_engine: AsyncEngine
) -> None:
    await run_alembic(migrated_database, "downgrade", PREVIOUS_REVISION)
    try:
        async with migrator_engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO meta.tenant (tenant_id, name) VALUES (:t, 'Migration test')"),
                {"t": MIGRATION_TENANT},
            )
            release_id = str(
                (
                    await connection.execute(
                        text("INSERT INTO meta.ref_data_release (code) VALUES (:c) RETURNING id"),
                        {"c": MIGRATION_RELEASE},
                    )
                ).scalar_one()
            )
            observed = (await connection.execute(text("SELECT date_trunc('second', now())"))).scalar_one()
            await connection.execute(
                text(
                    "INSERT INTO geo.event_location (tenant_id, event_id, observed_at, event_type, "
                    "source_type, location_source, geom) VALUES (:t, 'evt-migrate-1', :o, 'test.event', "
                    "'sensor', 'sensor', public.ST_GeomFromText('POINT(80.75 8.03)', 4326))"
                ),
                {"t": MIGRATION_TENANT, "o": observed},
            )
            previous = _previous_document(release_id, observed.isoformat())
            await connection.execute(
                text(
                    "INSERT INTO geo.event_geo_context (tenant_id, event_id, observed_at, release_id, "
                    "release_code, location_source, admin_l1_code, document) "
                    "VALUES (:t, 'evt-migrate-1', :o, :r, :c, 'sensor', 'P1', CAST(:d AS jsonb))"
                ),
                {
                    "t": MIGRATION_TENANT,
                    "o": observed,
                    "r": release_id,
                    "c": MIGRATION_RELEASE,
                    "d": json.dumps(previous),
                },
            )

        await run_alembic(migrated_database, "upgrade", "head")
        async with migrator_engine.connect() as connection:
            converted = (
                await connection.execute(text("SELECT document FROM geo.event_geo_context"))
            ).scalar_one()
        context = GeoContext.model_validate(converted)
        assert context.ref_data_release == MIGRATION_RELEASE
        assert context.tenant_id == MIGRATION_TENANT
        assert context.admin.codes.model_dump() == {"l1": "P1", "l2": None, "l3": None, "l4": None}
        assert context.nearest_settlement is not None
        assert context.nearest_settlement.basis == "footprint"
        assert [(z.zone_type, z.severity) for z in context.inside_zones] == [("risk_zone", 3)]
        assert [(h.kind, h.tenant_id, h.relation) for h in context.geofence_hits] == [
            ("circle", MIGRATION_TENANT, "intersects")
        ]
        assert [(d.device_id, d.tenant_id, d.in_field_of_view) for d in context.nearest_devices] == [
            (uuid.UUID("0192f1a0-0000-7000-8000-000000000005"), MIGRATION_TENANT, None)
        ]
        assert context.missing_layers == ["admin_area", "settlement", "road", "protected_area", "risk_zone"]
        async with migrator_engine.begin() as connection, connection.begin_nested() as savepoint:
            with pytest.raises(Exception, match="ck_event_geo_context_document"):
                await connection.execute(
                    text("UPDATE geo.event_geo_context SET document = document - 'insideZones'")
                )
            await savepoint.rollback()

        await run_alembic(migrated_database, "downgrade", PREVIOUS_REVISION)
        async with migrator_engine.connect() as connection:
            restored = (
                await connection.execute(text("SELECT document FROM geo.event_geo_context"))
            ).scalar_one()
        assert restored == previous
    finally:
        async with migrator_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM geo.event_location WHERE tenant_id = :t"), {"t": MIGRATION_TENANT}
            )
            await connection.execute(
                text("DELETE FROM meta.ref_data_release WHERE code = :c"), {"c": MIGRATION_RELEASE}
            )
            await connection.execute(
                text("DELETE FROM meta.tenant WHERE tenant_id = :t"), {"t": MIGRATION_TENANT}
            )
        await run_alembic(migrated_database, "upgrade", "head")
