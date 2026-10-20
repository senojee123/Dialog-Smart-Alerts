"""Shared helpers for Alembic revisions.

Revisions import this module (``env.py`` puts ``db/migrations`` on ``sys.path``). Keep every helper
backwards compatible: already-applied revisions call these functions when they are replayed on a
fresh database.

SQL built here only ever interpolates identifiers that come from revision constants, or the runtime
role name, which is validated against a strict pattern and quoted by the dialect. Values are bound
parameters.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_QUALIFIED_NAME = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")


def app_role() -> str:
    """Quoted name of the runtime login, validated and (online) checked to exist."""
    context = op.get_context()
    if context.config is None:
        raise RuntimeError("migrations must be run through Alembic's command interface")
    role = context.config.attributes["gis_app_role"]
    if not _ROLE_NAME.fullmatch(role):
        raise RuntimeError(f"invalid runtime role name: {role!r}")
    if not context.as_sql:
        exists = op.get_bind().execute(
            sa.text("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :role"), {"role": role}
        )
        if exists.scalar_one_or_none() is None:
            raise RuntimeError(
                f"runtime role {role!r} does not exist; create it before migrating (see db/init/)"
            )
    return str(context.dialect.identifier_preparer.quote_identifier(role))


def literal(value: str) -> str:
    """Quote a string constant defined in a revision as an SQL literal."""
    return "'" + value.replace("'", "''") + "'"


def qualified(name: str) -> str:
    """Validate a ``schema.table`` constant before it is interpolated into DDL."""
    if not _QUALIFIED_NAME.fullmatch(name):
        raise ValueError(f"not a plain schema-qualified name: {name!r}")
    return name


def short_name(name: str) -> str:
    return qualified(name).split(".", 1)[1]


def refuse_if_not_empty(tables: Sequence[str]) -> None:
    """Downgrades never discard data silently: fail if any of the tables still holds rows."""
    for table in tables:
        name = qualified(table)  # validated identifier from a revision, never input
        statement = f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM {name}) THEN
                    RAISE EXCEPTION 'downgrade refused: {name} contains rows; export or delete them first'
                        USING ERRCODE = '55000';
                END IF;
            END
            $$
            """  # noqa: S608
        op.execute(statement)


def comment_table(table: str, comment: str) -> None:
    op.execute(f"COMMENT ON TABLE {qualified(table)} IS {literal(comment)}")


def comment_columns(table: str, comments: dict[str, str]) -> None:
    for column, comment in comments.items():
        op.execute(f"COMMENT ON COLUMN {qualified(table)}.{column} IS {literal(comment)}")


def geometry_checks(table: str, column: str = "geom", *, nullable: bool = False) -> str:
    """CHECK constraints shared by every canonical geometry column (EPSG:4326).

    ``ST_IsValid(g, 0)`` is used rather than ``ST_IsValid(g)``: same result, without a NOTICE per row.
    """
    name = short_name(table)
    prefix = f"{column} IS NULL OR " if nullable else ""
    return (
        f"CONSTRAINT ck_{name}_{column}_valid CHECK ({prefix}public.ST_IsValid({column}, 0)),\n"
        f"CONSTRAINT ck_{name}_{column}_not_empty CHECK ({prefix}NOT public.ST_IsEmpty({column})),\n"
        f"CONSTRAINT ck_{name}_{column}_in_service_area CHECK ({prefix}meta.is_within_sri_lanka({column}))"
    )


def metric_twin(column: str = "geom", geometry_type: str = "Geometry") -> str:
    """Stored EPSG:5235 copy of a canonical geometry column, maintained by PostgreSQL."""
    return (
        f"{column}_metric public.geometry({geometry_type}, 5235) "
        f"GENERATED ALWAYS AS (public.ST_Transform({column}, 5235)) STORED"
    )


def version_trigger(table: str) -> None:
    """Increment ``version`` on every update (optimistic concurrency)."""
    op.execute(
        f"CREATE TRIGGER a80_bump_row_version BEFORE UPDATE ON {qualified(table)} "
        "FOR EACH ROW EXECUTE FUNCTION meta.bump_row_version()"
    )


def touch_trigger(table: str) -> None:
    """Keep ``updated_at`` current on every update."""
    op.execute(
        f"CREATE TRIGGER a90_touch_updated_at BEFORE UPDATE ON {qualified(table)} "
        "FOR EACH ROW EXECUTE FUNCTION meta.touch_updated_at()"
    )


def gist_index(table: str, column: str, *, name: str | None = None, extra: str = "") -> None:
    index = name or f"ix_{short_name(table)}_{column}_gist"
    op.execute(f"CREATE INDEX {index} ON {qualified(table)} USING gist ({column}){extra}")


def register_layer(
    *,
    code: str,
    name: str,
    description: str,
    layer_group: str,
    geometry_types: Sequence[str],
    tenant_scoped: bool,
    default_sharing_policy: str | None,
    update_frequency: str,
    nominal_accuracy_m: float | None,
    geometry_column: str = "geom",
) -> None:
    """Add a row to meta.layer. ``code`` is also the schema-qualified table name."""
    schema, table = qualified(code).split(".", 1)
    op.execute(
        sa.text(
            """
            INSERT INTO meta.layer (
                code, name, description, layer_group, table_schema, table_name, geometry_column,
                geometry_types, tenant_scoped, default_sharing_policy, update_frequency, nominal_accuracy_m
            ) VALUES (
                :code, :name, :description, :layer_group, :schema, :table, :geometry_column,
                string_to_array(:geometry_types, ','), :tenant_scoped, :default_sharing_policy,
                :update_frequency, :nominal_accuracy_m
            )
            """
        ).bindparams(
            code=code,
            name=name,
            description=description,
            layer_group=layer_group,
            schema=schema,
            table=table,
            geometry_column=geometry_column,
            geometry_types=",".join(geometry_types),
            tenant_scoped=tenant_scoped,
            default_sharing_policy=default_sharing_policy,
            update_frequency=update_frequency,
            nominal_accuracy_m=nominal_accuracy_m,
        )
    )


def unregister_layers(codes: Sequence[str]) -> None:
    for code in codes:
        op.execute(sa.text("DELETE FROM meta.layer WHERE code = :code").bindparams(code=qualified(code)))


def tenant_policies(table: str, read_using: str) -> None:
    """Row-level security: read by ``read_using``; write only rows of the current tenant."""
    tbl = qualified(table)
    name = short_name(table)
    own = "tenant_id = meta.current_tenant_id()"
    op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {name}_select ON {tbl} FOR SELECT USING ({read_using})")
    op.execute(f"CREATE POLICY {name}_insert ON {tbl} FOR INSERT WITH CHECK ({own})")
    op.execute(f"CREATE POLICY {name}_update ON {tbl} FOR UPDATE USING ({own}) WITH CHECK ({own})")
    op.execute(f"CREATE POLICY {name}_delete ON {tbl} FOR DELETE USING ({own})")
