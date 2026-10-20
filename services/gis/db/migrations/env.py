"""Alembic environment for the GIS Core Service.

* Connects with the migration login (``GIS_DB_MIGRATOR_USER`` / ``GIS_DB_MIGRATOR_PASSWORD``), which
  owns the application schemas. The runtime API login never runs DDL.
* Uses the asyncpg driver, like the application.
* Callers that already hold a connection (the test suite) pass it in ``config.attributes["connection"]``.
* Revisions share helpers from ``migration_support.py`` in this directory (on ``sys.path`` through
  ``prepend_sys_path`` in ``alembic.ini``).
* Monthly partitions of the ``geo`` event tables (``*_pYYYYMM``) are created at runtime by
  ``geo.ensure_event_partition()``; autogenerate ignores them.
"""

from __future__ import annotations

import asyncio
import re
from logging.config import fileConfig

from alembic import context
from alembic.environment import NameFilterParentNames, NameFilterType
from sqlalchemy import ForeignKeyConstraint, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.sql.schema import SchemaItem

import app.models  # noqa: F401  (registers all ORM models on Base.metadata)
from app.core.config import DbRole, get_settings
from app.db.base import APPLICATION_SCHEMAS, Base
from app.db.engine import connect_args

EVENT_PARTITION = re.compile(r"_p[0-9]{6}$")

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging_config"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

settings = get_settings()
# Migrations read the runtime role name from here, so they never import application settings directly.
config.attributes.setdefault("gis_app_role", settings.db_app_user)

target_metadata = Base.metadata


def include_name(name: str | None, type_: NameFilterType, parent_names: NameFilterParentNames) -> bool:
    if type_ == "schema":
        return name in APPLICATION_SCHEMAS
    # Monthly partitions are runtime objects, not part of the declared schema.
    return not (type_ == "table" and name is not None and EVENT_PARTITION.search(name))


def include_object(
    object_: SchemaItem,
    name: str | None,
    type_: NameFilterType,
    reflected: bool,
    compare_to: SchemaItem | None,
) -> bool:
    # PostgreSQL adds one internal foreign key per partition of a partitioned referenced table.
    if type_ == "foreign_key_constraint" and isinstance(object_, ForeignKeyConstraint):
        return not EVENT_PARTITION.search(object_.referred_table.name)
    return True


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
        transaction_per_migration=True,
    )


def do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(
        settings.database_url(DbRole.MIGRATOR),
        poolclass=pool.NullPool,
        connect_args=connect_args(settings, DbRole.MIGRATOR),
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_offline() -> None:
    """Emit SQL to stdout (``alembic upgrade head --sql``) for review by a DBA."""
    context.configure(
        dialect_name="postgresql",
        # Named parameters: '%' in PL/pgSQL bodies (RAISE ... %) must reach the script unescaped.
        dialect_opts={"paramstyle": "named"},
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        literal_binds=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
