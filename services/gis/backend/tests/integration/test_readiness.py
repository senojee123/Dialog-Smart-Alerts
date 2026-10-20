"""Readiness against a real database, through the HTTP API."""

from __future__ import annotations

import httpx
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.main import create_app
from app.services.readiness import CheckStatus, ReadinessService
from tests.integration.conftest import reset_database, run_alembic

EXPECTED_CHECKS = [
    "database",
    "postgis",
    "spatial_reference_systems",
    "crs_consistency",
    "tenant_spatial_indexes",
    "migrations",
]


async def test_ready_when_database_is_migrated(migrated_database: Settings) -> None:
    app = create_app(migrated_database)
    async with (
        LifespanManager(app) as manager,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=manager.app), base_url="http://test") as client,
    ):
        response = await client.get("/health/ready")
    body = response.json()
    assert response.status_code == 200, body
    assert body["status"] == "ready"
    assert [check["name"] for check in body["checks"]] == EXPECTED_CHECKS
    checks = {check["name"]: check for check in body["checks"]}
    assert checks["database"]["detail"]["database"] == migrated_database.db_name
    assert checks["spatial_reference_systems"]["detail"]["missing"] == []
    assert checks["crs_consistency"]["status"] == "pass"
    # The test database is initialised like the container (db/init): the && operator is leakproof.
    assert checks["tenant_spatial_indexes"]["status"] == "pass", checks["tenant_spatial_indexes"]
    assert checks["migrations"]["detail"]["applied"] == checks["migrations"]["detail"]["expected"]
    assert "/" not in checks["postgis"]["detail"]["projVersion"], "build paths must not be exposed"


async def test_not_ready_when_build_expects_a_newer_revision(
    migrated_database: Settings, app_engine: AsyncEngine
) -> None:
    service = ReadinessService(app_engine, migrated_database, frozenset({"99999999_9999"}))
    report = await service.check()
    migrations = next(check for check in report.checks if check.name == "migrations")
    assert not report.ready
    assert migrations.status is CheckStatus.FAIL
    assert migrations.error == "database schema revision does not match this build"


async def test_not_ready_before_migrations_run(migrated_database: Settings, app_engine: AsyncEngine) -> None:
    # Empty the schema first: a downgrade refuses to drop tables that still hold another test's rows.
    await reset_database(migrated_database)
    await run_alembic(migrated_database, "downgrade", "base")
    try:
        service = ReadinessService(app_engine, migrated_database, frozenset({"20260915_0001"}))
        report = await service.check()
    finally:
        await run_alembic(migrated_database, "upgrade", "head")
    migrations = next(check for check in report.checks if check.name == "migrations")
    assert not report.ready
    assert migrations.status is CheckStatus.FAIL
    assert migrations.error == "database has not been migrated"


async def test_postgis_minimum_version_is_enforced(
    migrated_database: Settings, app_engine: AsyncEngine
) -> None:
    demanding = migrated_database.model_copy(update={"postgis_min_version": "99.0"})
    report = await ReadinessService(app_engine, demanding, frozenset({"20260915_0001"})).check()
    postgis = next(check for check in report.checks if check.name == "postgis")
    assert postgis.status is CheckStatus.FAIL
    assert not report.ready
