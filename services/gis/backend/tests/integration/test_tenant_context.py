"""Tenant context must be transaction-scoped (ADR-09, risk R6)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.core.config import DbRole, Settings
from app.core.tenancy import TenantId
from app.db.engine import connect_args, create_session_factory
from app.db.session import transaction

CURRENT = text("SELECT meta.current_tenant_id() AS tenant, pg_backend_pid() AS pid")


@pytest.fixture
async def single_connection_factory(
    migrated_database: Settings,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A pool with exactly one connection, so consecutive transactions reuse the same backend."""
    engine: AsyncEngine = create_async_engine(
        migrated_database.database_url(DbRole.APP),
        poolclass=AsyncAdaptedQueuePool,
        pool_size=1,
        max_overflow=0,
        connect_args=connect_args(migrated_database, DbRole.APP),
    )
    yield create_session_factory(engine)
    await engine.dispose()


async def test_tenant_is_visible_inside_the_transaction_only(
    single_connection_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with transaction(single_connection_factory, TenantId("tenant-a")) as session:
        inside = (await session.execute(CURRENT)).one()
    assert inside.tenant == "tenant-a"

    async with transaction(single_connection_factory) as session:
        after = (await session.execute(CURRENT)).one()
    assert after.pid == inside.pid, "the test must reuse the pooled connection"
    assert after.tenant is None


async def test_tenant_does_not_survive_a_rolled_back_transaction(
    single_connection_factory: async_sessionmaker[AsyncSession],
) -> None:
    class SimulatedFailureError(Exception):
        pass

    async def failing_request() -> None:
        async with transaction(single_connection_factory, TenantId("tenant-b")) as session:
            assert (await session.execute(CURRENT)).one().tenant == "tenant-b"
            raise SimulatedFailureError

    with pytest.raises(SimulatedFailureError):
        await failing_request()

    async with transaction(single_connection_factory) as session:
        assert (await session.execute(CURRENT)).one().tenant is None


async def test_tenants_do_not_bleed_between_sequential_requests(
    single_connection_factory: async_sessionmaker[AsyncSession],
) -> None:
    seen = []
    for tenant in ("tenant-a", "tenant-b", "tenant-c"):
        async with transaction(single_connection_factory, TenantId(tenant)) as session:
            seen.append((await session.execute(CURRENT)).one().tenant)
    assert seen == ["tenant-a", "tenant-b", "tenant-c"]


async def test_tenant_value_is_bound_not_interpolated(
    single_connection_factory: async_sessionmaker[AsyncSession],
) -> None:
    # TenantId already rejects this, which is the first line of defence.
    with pytest.raises(ValueError, match="tenant id"):
        TenantId("x'); DROP SCHEMA ops; --")
    async with transaction(single_connection_factory) as session:
        exists = (await session.execute(text("SELECT to_regnamespace('ops') IS NOT NULL"))).scalar_one()
    assert exists
