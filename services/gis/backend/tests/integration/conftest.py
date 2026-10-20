"""Integration test fixtures: a real PostgreSQL + PostGIS database.

Connection settings come from the usual ``GIS_DB_*`` variables. Both logins are needed:
``GIS_DB_MIGRATOR_PASSWORD`` (migrations) and ``GIS_DB_APP_PASSWORD`` (runtime checks).

Safety: the suite migrates the database down to an empty schema and back up. It refuses to run
unless ``GIS_DB_NAME`` ends in ``_test``.

When no database is reachable the tests are skipped; set ``GIS_REQUIRE_DB=1`` (as CI and the
``backend-tests`` Compose service do) to turn that into a failure.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import DbRole, Settings
from app.db.base import APPLICATION_SCHEMAS
from app.db.engine import create_engine, create_session_factory
from app.db.session import transaction
from app.services.reference_loader import LoadResult, ReferenceDataLoader
from app.spatial.service_area import ServiceArea
from tests.integration.spatial_world import (
    EVENT_TEST_MONTHS,
    OPEN_MANIFEST,
    SYNTHETIC_MANIFEST,
    TENANTS,
    OpsWorld,
    build_ops_world,
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.integration)


def _unavailable(reason: str) -> None:
    if os.environ.get("GIS_REQUIRE_DB") == "1":
        pytest.fail(f"integration database required but unavailable: {reason}", pytrace=False)
    pytest.skip(f"integration database unavailable: {reason}")


@pytest.fixture(scope="session")
def db_settings() -> Settings:
    settings = Settings()
    if os.environ.get("GIS_DB_APP_PASSWORD") in (None, "placeholder-not-used-by-unit-tests"):
        _unavailable("GIS_DB_APP_PASSWORD is not set")
    if settings.db_migrator_password is None:
        _unavailable("GIS_DB_MIGRATOR_PASSWORD is not set")
    if not settings.db_name.endswith("_test"):
        pytest.fail(
            f"refusing to run destructive integration tests against database {settings.db_name!r}; "
            "point GIS_DB_NAME at a database whose name ends in '_test'",
            pytrace=False,
        )
    return settings


def alembic_config(settings: Settings) -> Config:
    config = Config(str(settings.alembic_config_path))
    config.attributes["skip_logging_config"] = True
    config.attributes["gis_app_role"] = settings.db_app_user
    return config


async def run_alembic(settings: Settings, action: str, revision: str) -> None:
    """Run an Alembic command on a connection owned by the test (see db/migrations/env.py)."""
    engine = create_engine(settings, DbRole.MIGRATOR)
    config = alembic_config(settings)

    def _run(connection: Connection) -> None:
        config.attributes["connection"] = connection
        getattr(command, action)(config, revision)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


_DATA_TABLES = text(
    """
    SELECT format('%I.%I', schemaname, tablename)
    FROM pg_catalog.pg_tables
    WHERE schemaname = ANY(:schemas) AND NOT (schemaname = 'meta' AND tablename = 'layer')
    ORDER BY 1
    """
)


async def reset_database(settings: Settings) -> None:
    """Empty every application table (the layer registry belongs to the migrations), then rebuild the
    schema from scratch. Downgrades refuse to drop tables that still hold rows."""
    engine = create_engine(settings, DbRole.MIGRATOR)
    try:
        async with engine.begin() as connection:
            tables = (
                (await connection.execute(_DATA_TABLES, {"schemas": list(APPLICATION_SCHEMAS)}))
                .scalars()
                .all()
            )
            if tables:
                # The audit log refuses TRUNCATE for every login; clearing it is a deliberate act.
                append_only = [table for table in tables if table == "audit.entry"]
                for table in append_only:
                    await connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
                # Table names come from the catalogue, quoted by format('%I.%I').
                await connection.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
                for table in append_only:
                    await connection.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
    finally:
        await engine.dispose()
    await run_alembic(settings, "downgrade", "base")
    await run_alembic(settings, "upgrade", "head")


@pytest.fixture(scope="session")
async def migrator_engine(db_settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(db_settings, DbRole.MIGRATOR)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depends on the environment
        await engine.dispose()
        _unavailable(f"cannot connect as {db_settings.db_migrator_user}: {type(exc).__name__}")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def migrated_database(db_settings: Settings, migrator_engine: AsyncEngine) -> Settings:
    """Start every session from a clean schema at the migration head."""
    await reset_database(db_settings)
    return db_settings


@pytest.fixture(scope="session")
async def app_engine(migrated_database: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(migrated_database, DbRole.APP)
    yield engine
    await engine.dispose()


@dataclass(frozen=True, slots=True)
class SpatialWorld:
    """A freshly migrated database with reference fixtures, tenants and operational data."""

    settings: Settings
    service_area: ServiceArea
    app_engine: AsyncEngine
    migrator_engine: AsyncEngine
    app_sessions: async_sessionmaker[AsyncSession]
    migrator_sessions: async_sessionmaker[AsyncSession]
    open_data: LoadResult
    synthetic: LoadResult
    ops: OpsWorld


@pytest.fixture(scope="module")
async def spatial_world(db_settings: Settings, migrator_engine: AsyncEngine) -> AsyncIterator[SpatialWorld]:
    """Module-scoped, so that tests which migrate the database down cannot leave other modules without data.

    Fresh engines are used because the schema is recreated (pooled connections cache statement plans).
    """
    await reset_database(db_settings)
    area = ServiceArea.from_bbox(db_settings.service_area_bbox)
    migrator = create_engine(db_settings, DbRole.MIGRATOR)
    app = create_engine(db_settings, DbRole.APP)
    migrator_sessions = create_session_factory(migrator)
    app_sessions = create_session_factory(app)
    try:
        async with transaction(migrator_sessions) as session:
            loader = ReferenceDataLoader(session, area)
            open_data = await loader.load(OPEN_MANIFEST, make_current=True)
            synthetic = await loader.load(SYNTHETIC_MANIFEST, publish=True)
            await session.execute(
                text("INSERT INTO meta.tenant (tenant_id, name, kind) VALUES (:tenant_id, :name, :kind)"),
                [{"tenant_id": t, "name": n, "kind": k} for t, n, k in TENANTS],
            )
            # Months the tests observe events in, independent of when the suite runs.
            for month in EVENT_TEST_MONTHS:
                await session.execute(text("SELECT geo.create_event_partitions(:month)"), {"month": month})
        ops = await build_ops_world(app_sessions)
        yield SpatialWorld(
            settings=db_settings,
            service_area=area,
            app_engine=app,
            migrator_engine=migrator,
            app_sessions=app_sessions,
            migrator_sessions=migrator_sessions,
            open_data=open_data,
            synthetic=synthetic,
            ops=ops,
        )
    finally:
        await app.dispose()
        await migrator.dispose()
