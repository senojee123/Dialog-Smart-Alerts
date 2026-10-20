"""Declarative base and database schema names.

Schemas (created by migration 0001):

* ``ref``   national reference data (admin boundaries, settlements, roads, ...); read-only at runtime
* ``ops``   tenant-owned operational data (sites, devices, geofences); row-level security
* ``geo``   event locations and geo-context results
* ``meta``  layer registry, reference data releases, lineage, tenant helper functions
* ``audit`` append-only audit records
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA_REF: Final = "ref"
SCHEMA_OPS: Final = "ops"
SCHEMA_GEO: Final = "geo"
SCHEMA_META: Final = "meta"
SCHEMA_AUDIT: Final = "audit"
APPLICATION_SCHEMAS: Final = (SCHEMA_REF, SCHEMA_OPS, SCHEMA_GEO, SCHEMA_META, SCHEMA_AUDIT)

# Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION: Final = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
