"""The ORM models mirror the migrations exactly (tables, columns, types, nullability, defaults, keys,
indexes and generated expressions). Comments are documentation and live only in the migrations."""

from __future__ import annotations

import importlib.util
import sys
import warnings
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

import app.models  # noqa: F401  (registers every model)
from app.core.config import REPOSITORY_ROOT, DbRole, Settings
from app.db.base import APPLICATION_SCHEMAS, Base
from app.db.engine import create_engine

COMMENT_DIFFS = {"modify_comment", "add_table_comment", "remove_table_comment"}


def _flatten(diffs: list[Any]) -> list[tuple[Any, ...]]:
    flat: list[tuple[Any, ...]] = []
    for diff in diffs:
        flat.extend(diff if isinstance(diff, list) else [diff])
    return flat


def _include_name(name: str | None, type_: str, parent_names: Any) -> bool:
    if type_ == "schema":
        return name in APPLICATION_SCHEMAS
    return not (type_ == "table" and name is not None and name[-8:-6] == "_p" and name[-6:].isdigit())


def _include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    if type_ == "foreign_key_constraint" and isinstance(obj, ForeignKeyConstraint):
        referred = obj.referred_table.name
        return not (referred[-8:-6] == "_p" and referred[-6:].isdigit())
    return True


def _compare(connection: Connection) -> list[tuple[Any, ...]]:
    context = MigrationContext.configure(
        connection,
        opts={
            "include_schemas": True,
            "include_name": _include_name,
            "include_object": _include_object,
            "compare_type": True,
            "compare_server_default": True,
            "target_metadata": Base.metadata,
        },
    )
    return _flatten(compare_metadata(context, Base.metadata))


async def test_models_match_the_migrated_schema(
    migrated_database: Settings, migrator_engine: AsyncEngine
) -> None:
    engine = create_engine(migrated_database, DbRole.MIGRATOR)
    try:
        async with engine.connect() as connection:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                diffs = await connection.run_sync(_compare)
    finally:
        await engine.dispose()
    significant = [diff for diff in diffs if diff[0] not in COMMENT_DIFFS]
    assert significant == []
    assert [str(w.message) for w in caught if "Computed" in str(w.message)] == []
    assert len(Base.metadata.tables) == 27


async def test_generated_schema_documents_are_current(migrated_database: Settings) -> None:
    """docs/database/SCHEMA.md and ERD.md describe exactly what the migrations create."""
    path = REPOSITORY_ROOT / "db" / "tools" / "generate_schema_docs.py"
    spec = importlib.util.spec_from_file_location("generate_schema_docs", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    documents = await module.generate()
    stale = [
        str(target.relative_to(REPOSITORY_ROOT))
        for target, content in documents.items()
        if target.read_text(encoding="utf-8") != content
    ]
    assert stale == [], "run: python ../db/tools/generate_schema_docs.py"
