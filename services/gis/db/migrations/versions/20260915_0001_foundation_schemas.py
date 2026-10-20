"""Foundation: PostGIS, application schemas, runtime grants and tenant helper.

Creates the platform the GIS feature migrations build on:

* PostGIS in schema ``public`` (a no-op when the database administrator already created it) and a
  guard that the coordinate systems the service depends on are present.
* Schemas ``ref``, ``ops``, ``geo``, ``meta`` and ``audit`` owned by the migration login.
* Default privileges so that tables created by later migrations are usable by the runtime login
  with least privilege (read-only reference data, append-only audit).
* ``meta.current_tenant_id()`` for row-level security policies (ADR-09).

SQL identifiers below come from module constants or from the runtime role name, which is validated
against a strict pattern and quoted by the dialect. No value originates from a client.

Revision ID: 20260915_0001
Revises:
Create Date: 2026-09-15 00:00:00+00:00
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = {
    "ref": "National reference geodata (admin boundaries, settlements, roads, protected areas). "
    "Read-only at runtime.",
    "ops": "Tenant-owned operational geodata (sites, devices, geofences). Protected by row-level security.",
    "geo": "Event locations and geo-context enrichment results.",
    "meta": "Layer registry, reference data releases, lineage and database helper functions.",
    "audit": "Append-only audit records for spatial searches, geofence changes and data releases.",
}

# Privileges the runtime login receives on tables and sequences that later migrations create.
TABLE_PRIVILEGES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ref", "meta"), "SELECT"),
    (("ops", "geo"), "SELECT, INSERT, UPDATE, DELETE"),
    (("audit",), "SELECT, INSERT"),
)
SEQUENCE_PRIVILEGES: tuple[tuple[str, ...], str] = (("ops", "geo", "audit"), "USAGE, SELECT")

TENANT_FUNCTION_COMMENT = (
    "Tenant of the current transaction, set by the API with "
    "set_config('gis.tenant_id', <tenant>, true). NULL when no tenant is set. "
    "Used by row-level security policies."
)

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _app_role() -> str:
    """Quoted runtime role name, validated and checked to exist."""
    context = op.get_context()
    if context.config is None:
        raise RuntimeError("migrations must be run through Alembic's command interface")
    role = context.config.attributes["gis_app_role"]
    if not _ROLE_NAME.fullmatch(role):
        raise RuntimeError(f"invalid runtime role name: {role!r}")
    if not context.as_sql:  # offline (--sql) mode has no connection to check against
        exists = op.get_bind().execute(
            sa.text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role"), {"role": role}
        )
        if exists.scalar_one_or_none() is None:
            raise RuntimeError(
                f"runtime role {role!r} does not exist; create it before migrating (see db/init/)"
            )
    return str(context.dialect.identifier_preparer.quote_identifier(role))


def _literal(value: str) -> str:
    """Quote a string constant defined in this module as an SQL literal."""
    return "'" + value.replace("'", "''") + "'"


def _default_privileges(action: str, app_role: str) -> None:
    direction = "TO" if action == "GRANT" else "FROM"
    for schemas, privileges in TABLE_PRIVILEGES:
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {', '.join(schemas)} "
            f"{action} {privileges} ON TABLES {direction} {app_role}"
        )
    schemas, privileges = SEQUENCE_PRIVILEGES
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {', '.join(schemas)} "
        f"{action} {privileges} ON SEQUENCES {direction} {app_role}"
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_extension e
                JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
                WHERE e.extname = 'postgis' AND n.nspname = 'public'
            ) THEN
                RAISE EXCEPTION 'PostGIS must be installed in schema public';
            END IF;
            IF (SELECT count(*) FROM public.spatial_ref_sys WHERE srid IN (3857, 4326, 5235)) <> 3 THEN
                RAISE EXCEPTION 'spatial_ref_sys must contain EPSG:3857, EPSG:4326 and EPSG:5235';
            END IF;
        END
        $$
        """
    )

    for name, comment in SCHEMAS.items():
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {name}")
        op.execute(f"COMMENT ON SCHEMA {name} IS {_literal(comment)}")

    app_role = _app_role()
    op.execute(f"GRANT USAGE ON SCHEMA {', '.join(SCHEMAS)} TO {app_role}")
    _default_privileges("GRANT", app_role)
    # Readiness compares the applied revision with the build's expected head.
    op.execute(f"GRANT SELECT ON TABLE public.alembic_version TO {app_role}")

    op.execute(
        """
        CREATE FUNCTION meta.current_tenant_id()
        RETURNS text
        LANGUAGE sql
        STABLE
        PARALLEL SAFE
        AS $$ SELECT NULLIF(pg_catalog.current_setting('gis.tenant_id', true), '') $$
        """
    )
    op.execute(f"COMMENT ON FUNCTION meta.current_tenant_id() IS {_literal(TENANT_FUNCTION_COMMENT)}")
    op.execute("REVOKE ALL ON FUNCTION meta.current_tenant_id() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION meta.current_tenant_id() TO {app_role}")


def downgrade() -> None:
    app_role = _app_role()
    op.execute("DROP FUNCTION IF EXISTS meta.current_tenant_id()")
    # SELECT on public.alembic_version is kept: the table outlives this revision and readiness must
    # still be able to report "not migrated" after a downgrade to base.
    _default_privileges("REVOKE", app_role)
    op.execute(f"REVOKE USAGE ON SCHEMA {', '.join(SCHEMAS)} FROM {app_role}")
    # RESTRICT: refuse to drop a schema that still holds objects rather than silently deleting data.
    for name in reversed(list(SCHEMAS)):
        op.execute(f"DROP SCHEMA IF EXISTS {name} RESTRICT")
    # PostGIS is left installed: it is shared infrastructure owned by the database administrator.
