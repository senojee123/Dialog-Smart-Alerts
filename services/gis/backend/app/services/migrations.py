"""Expected database revision, read from the Alembic scripts shipped with this build."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def load_migration_heads(alembic_config_path: Path) -> frozenset[str]:
    """Return the head revision(s) of the migration scripts.

    Raises ``FileNotFoundError`` if the Alembic configuration is missing, so a broken image fails
    readiness instead of silently reporting a healthy schema.
    """
    if not alembic_config_path.is_file():
        raise FileNotFoundError(f"Alembic configuration not found: {alembic_config_path}")
    config = Config(str(alembic_config_path))
    heads = ScriptDirectory.from_config(config).get_heads()
    if not heads:
        raise RuntimeError("no migration revisions found")
    return frozenset(heads)
