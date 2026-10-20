"""Column types and mixins shared by the ORM models.

The Alembic revisions in ``db/migrations/versions`` are the authoritative schema. The models mirror
their tables, columns, keys and indexes (``tests/integration/test_model_parity.py`` fails on any
difference) so that application code gets typed access. CHECK constraints, triggers, row-level
security and functions exist only in the migrations; see ``docs/database/SCHEMA.md``.

Relationships are deliberately not mapped: repositories issue explicit queries, which keeps loading
behaviour visible in async code.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import Computed, DateTime, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.spatial.crs import CANONICAL_SRID, METRIC_SRID

UUID_V7: Final = text("uuidv7()")
NOW: Final = text("now()")
EMPTY_JSON_OBJECT: Final = text("'{}'::jsonb")
CURRENT_TENANT: Final = text("meta.current_tenant_id()")

GEOMETRY_SOURCES: Final = ("survey", "gps", "digitised", "imagery", "osm", "derived", "synthetic", "unknown")
SHARING_POLICIES: Final = ("private", "shared", "authority_only")


def geometry(geometry_type: str, srid: int = CANONICAL_SRID) -> Geometry:
    """A typmod geometry column. Spatial indexes are declared explicitly on each table."""
    return Geometry(geometry_type=geometry_type, srid=srid, spatial_index=False)


def metric_twin(geometry_type: str, source: str = "geom") -> Mapped[WKBElement]:
    """Stored EPSG:5235 copy of a canonical geometry column, computed by PostgreSQL.

    Generation expressions are written as PostgreSQL prints them back (``pg_get_expr``), so that the
    parity test can compare them; the models never emit DDL.
    """
    return mapped_column(
        geometry(geometry_type, METRIC_SRID),
        Computed(f"st_transform({source}, {METRIC_SRID})", persisted=True),
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=UUID_V7)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=NOW)


def updated_at() -> Mapped[datetime]:
    """Maintained by the ``a90_touch_updated_at`` trigger."""
    return mapped_column(DateTime(timezone=True), server_default=NOW)


def attributes() -> Mapped[dict[str, Any]]:
    return mapped_column(JSONB, server_default=EMPTY_JSON_OBJECT)


def metres(precision: int = 10) -> Mapped[Decimal | None]:
    return mapped_column(Numeric(precision, 2))


def optional_text() -> Mapped[str | None]:
    return mapped_column(Text)
