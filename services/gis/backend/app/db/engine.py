"""Async SQLAlchemy engine factory (asyncpg driver)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app import SERVICE_NAME
from app.core.config import DbRole, DbSslMode, Settings


def connect_args(settings: Settings, role: DbRole) -> dict[str, object]:
    server_settings = {
        "application_name": f"{SERVICE_NAME}:{role.value}",
        "statement_timeout": str(settings.db_statement_timeout_ms),
        "idle_in_transaction_session_timeout": str(settings.db_idle_in_transaction_timeout_ms),
        "timezone": "UTC",
    }
    if role is DbRole.MIGRATOR:
        # DDL can legitimately take longer than an API query; lock waits must still be bounded.
        server_settings["statement_timeout"] = "0"
        server_settings["lock_timeout"] = "30000"
    args: dict[str, object] = {
        "server_settings": server_settings,
        "timeout": settings.db_connect_timeout_s,
    }
    if settings.db_ssl_mode is not DbSslMode.DISABLE:
        args["ssl"] = settings.db_ssl_mode.value
    else:
        args["ssl"] = False
    return args


def create_engine(settings: Settings, role: DbRole = DbRole.APP) -> AsyncEngine:
    return create_async_engine(
        settings.database_url(role),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_recycle=settings.db_pool_recycle_s,
        pool_pre_ping=True,
        # Bound parameters stay out of error messages and logs: they include searched positions and
        # object attributes (docs/security.md, privacy).
        hide_parameters=True,
        connect_args=connect_args(settings, role),
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
