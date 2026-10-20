"""Generate the schema reference and the ERD from a migrated database.

The catalogue is the source of truth, so the documents describe exactly what the migrations create:
tables, columns, generated expressions, comments, keys, CHECK and exclusion constraints, indexes,
triggers, row-level security policies, functions and the layer registry. Monthly event partitions are
left out (they are runtime objects).

Usage (from ``backend/``, ``GIS_DB_*`` pointing at a database migrated to head)::

    python ../db/tools/generate_schema_docs.py            # writes docs/database/SCHEMA.md and ERD.md
    python ../db/tools/generate_schema_docs.py --check    # fails if the files are out of date
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import REPOSITORY_ROOT, DbRole, get_settings
from app.db.base import APPLICATION_SCHEMAS
from app.db.engine import create_engine

OUTPUT_DIR = REPOSITORY_ROOT / "docs" / "database"
PARTITION = r"_p[0-9]{6}$"

TABLES_SQL = text(
    """
    SELECT c.oid, n.nspname AS schema, c.relname AS name, c.relkind::text AS kind,
           obj_description(c.oid, 'pg_class') AS comment, c.relrowsecurity AS rls,
           pg_get_partkeydef(c.oid) AS partition_key
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = ANY(:schemas) AND c.relkind IN ('r', 'p') AND c.relname !~ :partition
    ORDER BY array_position(:schemas, n.nspname::text), c.relname
    """
)
COLUMNS_SQL = text(
    """
    SELECT a.attrelid AS oid, a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type,
           a.attnotnull AS not_null, a.attgenerated::text AS generated, a.attidentity::text AS identity,
           pg_get_expr(d.adbin, d.adrelid) AS default_expr, col_description(a.attrelid, a.attnum) AS comment
    FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
    WHERE a.attrelid = ANY(:oids) AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY a.attrelid, a.attnum
    """
)
CONSTRAINTS_SQL = text(
    """
    SELECT con.conrelid AS oid, con.conname AS name, con.contype::text AS kind,
           pg_get_constraintdef(con.oid) AS definition,
           ARRAY(SELECT att.attname::text FROM unnest(con.conkey) WITH ORDINALITY AS k(num, ord)
                 JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k.num ORDER BY k.ord)
               AS columns,
           ref_ns.nspname || '.' || ref.relname AS referenced
    FROM pg_constraint con
    LEFT JOIN pg_class ref ON ref.oid = con.confrelid
    LEFT JOIN pg_namespace ref_ns ON ref_ns.oid = ref.relnamespace
    WHERE con.conrelid = ANY(:oids) AND con.conparentid = 0 AND con.contype <> 'n'
      AND (ref.relname IS NULL OR ref.relname !~ :partition)
    ORDER BY con.conrelid, array_position(ARRAY['p', 'f', 'u', 'x', 'c']::"char"[], con.contype), con.conname
    """
)
INDEXES_SQL = text(
    """
    SELECT i.indrelid AS oid, ic.relname AS name, am.amname AS method,
           pg_get_indexdef(i.indexrelid) AS definition,
           i.indisprimary AS is_primary, i.indisunique AS is_unique,
           EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = i.indexrelid) AS from_constraint
    FROM pg_index i
    JOIN pg_class ic ON ic.oid = i.indexrelid
    JOIN pg_am am ON am.oid = ic.relam
    WHERE i.indrelid = ANY(:oids)
    ORDER BY i.indrelid, ic.relname
    """
)
TRIGGERS_SQL = text(
    """
    SELECT t.tgrelid AS oid, t.tgname AS name, pg_get_triggerdef(t.oid) AS definition,
           p.pronamespace::regnamespace::text || '.' || p.proname AS function
    FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid
    WHERE t.tgrelid = ANY(:oids) AND NOT t.tgisinternal
    ORDER BY t.tgrelid, t.tgname
    """
)
POLICIES_SQL = text(
    """
    SELECT (quote_ident(schemaname) || '.' || quote_ident(tablename))::regclass::oid AS oid,
           policyname AS name, cmd, qual, with_check
    FROM pg_policies WHERE schemaname = ANY(:schemas) AND tablename !~ :partition
    ORDER BY schemaname, tablename, policyname
    """
)
FUNCTIONS_SQL = text(
    """
    SELECT n.nspname AS schema, p.proname AS name, pg_get_function_identity_arguments(p.oid) AS arguments,
           pg_get_function_result(p.oid) AS result, l.lanname AS language,
           CASE p.provolatile WHEN 'i' THEN 'immutable' WHEN 's' THEN 'stable' ELSE 'volatile' END
               AS volatility,
           p.prosecdef AS security_definer, obj_description(p.oid, 'pg_proc') AS comment
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace JOIN pg_language l ON l.oid = p.prolang
    WHERE n.nspname = ANY(:schemas)
    ORDER BY array_position(:schemas, n.nspname::text), p.proname
    """
)
SCHEMAS_SQL = text(
    """
    SELECT nspname AS name, obj_description(oid, 'pg_namespace') AS comment
    FROM pg_namespace WHERE nspname = ANY(:schemas) ORDER BY array_position(:schemas, nspname::text)
    """
)
LAYERS_SQL = text(
    """
    SELECT code, name, layer_group, array_to_string(geometry_types, ', ') AS geometry_types, tenant_scoped,
           coalesce(default_sharing_policy, '-') AS sharing, update_frequency, nominal_accuracy_m
    FROM meta.layer ORDER BY array_position(ARRAY['reference', 'operational', 'event'], layer_group), code
    """
)
REVISION_SQL = text("SELECT version_num FROM public.alembic_version")

# Relationships maintained by triggers or by the application rather than by foreign keys.
LOGICAL_LINKS = (
    ("ref.area_part", "ref.admin_area", "feature_id", "subdivided parts (trigger)"),
    ("ref.area_part", "ref.protected_area", "feature_id", "subdivided parts (trigger)"),
    ("ref.area_part", "ref.risk_zone", "feature_id", "subdivided parts (trigger)"),
    ("ref.area_part", "ref.water_body", "feature_id", "subdivided parts (trigger)"),
    ("meta.geometry_repair", "ref.admin_area", "feature_id", "repaired feature (any ref layer)"),
    ("geo.event_zone_hit", "ref.protected_area", "zone_id", "zone (by zone_kind)"),
    ("geo.event_zone_hit", "ref.risk_zone", "zone_id", "zone (by zone_kind)"),
    ("geo.event_geo_context", "ref.admin_area", "admin_l1_id..admin_l4_id", "admin hierarchy"),
    ("geo.event_geo_context", "ref.settlement", "nearest_settlement_id", "nearest settlement"),
    ("geo.event_geo_context", "ref.road", "nearest_road_id", "nearest road"),
)


@dataclass
class Table:
    oid: int
    schema: str
    name: str
    kind: str
    comment: str | None
    rls: bool
    partition_key: str | None
    columns: list[Any] = field(default_factory=list)
    constraints: list[Any] = field(default_factory=list)
    indexes: list[Any] = field(default_factory=list)
    triggers: list[Any] = field(default_factory=list)
    policies: list[Any] = field(default_factory=list)

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def anchor(self) -> str:
        return f"{self.schema}{self.name}".replace("_", "-")


def cell(value: object) -> str:
    if value is None or value == "":
        return ""
    return " ".join(str(value).split()).replace("|", "\\|")


def code(value: object) -> str:
    return f"`{cell(value)}`" if value not in (None, "") else ""


def table_md(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(value) for value in row) + " |" for row in rows]
    return lines


async def load(connection: AsyncConnection) -> dict[str, Any]:
    params = {"schemas": list(APPLICATION_SCHEMAS), "partition": PARTITION}
    tables = [Table(*row) for row in (await connection.execute(TABLES_SQL, params)).all()]
    by_oid = {table.oid: table for table in tables}
    oid_params = {"oids": list(by_oid), "partition": PARTITION}
    for attribute, sql, parameters in (
        ("columns", COLUMNS_SQL, oid_params),
        ("constraints", CONSTRAINTS_SQL, oid_params),
        ("indexes", INDEXES_SQL, oid_params),
        ("triggers", TRIGGERS_SQL, oid_params),
        ("policies", POLICIES_SQL, params),
    ):
        for row in (await connection.execute(sql, parameters)).all():
            if row.oid in by_oid:
                getattr(by_oid[row.oid], attribute).append(row)
    return {
        "schemas": (await connection.execute(SCHEMAS_SQL, params)).all(),
        "tables": tables,
        "functions": (await connection.execute(FUNCTIONS_SQL, params)).all(),
        "layers": (await connection.execute(LAYERS_SQL)).all(),
        "revision": ", ".join(sorted((await connection.execute(REVISION_SQL)).scalars())),
    }


TRIGGER = re.compile(
    r"^CREATE (?:CONSTRAINT )?TRIGGER \S+ (?P<events>.*?) ON \S+ .*?FOR EACH (?P<level>ROW|STATEMENT) "
    r"(?:WHEN \((?P<when>.*)\) )?EXECUTE FUNCTION (?P<call>.*)$"
)


def trigger_row(trigger: Any) -> tuple[str, str, str, str]:
    match = TRIGGER.match(trigger.definition)
    if match is None:
        return code(trigger.name), code(trigger.definition), "", ""
    fires = f"{match['events']} (per {match['level'].lower()})"
    return code(trigger.name), cell(fires), code(match["when"]), code(match["call"])


def column_default(column: Any) -> str:
    if column.generated == "s":
        return f"generated: {code(column.default_expr)}"
    if column.identity:
        return "identity"
    return code(column.default_expr)


def schema_markdown(model: dict[str, Any]) -> str:
    tables: list[Table] = model["tables"]
    out = [
        "# Database schema reference",
        "",
        "<!-- Generated by db/tools/generate_schema_docs.py from the database catalogue. Do not edit. -->",
        "",
        f"Migration head: `{model['revision']}`. Design notes: [README.md](README.md). "
        "Diagram: [ERD.md](ERD.md).",
        "",
        "## Schemas",
        "",
        *table_md(("Schema", "Purpose"), ((code(s.name), cell(s.comment)) for s in model["schemas"])),
        "",
        "## Tables",
        "",
        *table_md(
            ("Table", "Purpose", "RLS", "Partitioned"),
            (
                (
                    f"[`{t.qualified}`](#{t.anchor})",
                    cell(t.comment),
                    "yes" if t.rls else "",
                    code(t.partition_key),
                )
                for t in tables
            ),
        ),
        "",
        "## Layer registry (`meta.layer`)",
        "",
        *table_md(
            (
                "Layer",
                "Name",
                "Group",
                "Geometry types",
                "Tenant-scoped",
                "Default sharing",
                "Updates",
                "Accuracy (m)",
            ),
            (
                (
                    code(layer.code),
                    cell(layer.name),
                    layer.layer_group,
                    cell(layer.geometry_types),
                    "yes" if layer.tenant_scoped else "no",
                    layer.sharing,
                    layer.update_frequency,
                    cell(layer.nominal_accuracy_m),
                )
                for layer in model["layers"]
            ),
        ),
        "",
        "## Index catalogue",
        "",
        "Spatial (GiST on geometry), temporal (BRIN, and GiST on ranges) and other indexes. Indexes that",
        "back primary keys and unique constraints are listed with their tables.",
        "",
    ]
    catalogue = []
    for t in tables:
        for index in t.indexes:
            if index.from_constraint and index.method == "btree":
                continue
            columns = index.definition.split(" USING ", 1)[1]
            catalogue.append((code(index.name), code(t.qualified), index.method, code(columns)))
    out += table_md(("Index", "Table", "Method", "Definition"), catalogue)
    out.append("")

    for schema in model["schemas"]:
        out += [f"## Schema `{schema.name}`", ""]
        schema_tables = [t for t in tables if t.schema == schema.name]
        if not schema_tables:
            out += ["No tables yet.", ""]
        for t in schema_tables:
            out += [f'<a id="{t.anchor}"></a>', "", f"### `{t.qualified}`", "", cell(t.comment), ""]
            if t.partition_key:
                out += [
                    f"Partitioned by `{t.partition_key}`; monthly partitions `{t.name}_pYYYYMM` are "
                    "created by `geo.ensure_event_partition()`.",
                    "",
                ]
            out += table_md(
                ("Column", "Type", "Null", "Default / generated", "Description"),
                (
                    (
                        code(c.name),
                        code(c.type),
                        "" if c.not_null else "yes",
                        column_default(c),
                        cell(c.comment),
                    )
                    for c in t.columns
                ),
            )
            out += ["", "**Constraints**", ""]
            kinds = {"p": "primary key", "f": "foreign key", "u": "unique", "x": "exclusion", "c": "check"}
            out += table_md(
                ("Name", "Kind", "Definition"),
                ((code(c.name), kinds.get(c.kind, c.kind), code(c.definition)) for c in t.constraints),
            )
            other_indexes = [i for i in t.indexes if not i.from_constraint]
            if other_indexes:
                out += ["", "**Indexes**", ""]
                out += table_md(
                    ("Name", "Method", "Definition"),
                    (
                        (code(i.name), i.method, code(i.definition.split(" USING ", 1)[1]))
                        for i in other_indexes
                    ),
                )
            if t.triggers:
                out += ["", "**Triggers** (fire in name order)", ""]
                out += table_md(
                    ("Name", "Fires", "Condition", "Executes"), (trigger_row(tr) for tr in t.triggers)
                )
            if t.policies:
                out += ["", "**Row-level security policies**", ""]
                out += table_md(
                    ("Policy", "Command", "USING", "WITH CHECK"),
                    ((code(p.name), p.cmd, code(p.qual), code(p.with_check)) for p in t.policies),
                )
            elif t.rls:
                out += [
                    "",
                    "Row-level security is enabled without policies: no access for the runtime login.",
                ]
            out.append("")

    out += ["## Functions", ""]
    out += table_md(
        ("Function", "Returns", "Language", "Volatility", "Security", "Description"),
        (
            (
                code(f"{f.schema}.{f.name}({f.arguments})"),
                code(f.result),
                f.language,
                f.volatility,
                "definer" if f.security_definer else "invoker",
                cell(f.comment),
            )
            for f in model["functions"]
        ),
    )
    out.append("")
    return "\n".join(out)


def entity(name: str) -> str:
    return name.replace(".", "__")


def erd_markdown(model: dict[str, Any]) -> str:
    tables: list[Table] = model["tables"]
    lines = [
        "# Entity-relationship diagram",
        "",
        "<!-- Generated by db/tools/generate_schema_docs.py from the database catalogue. Do not edit. -->",
        "",
        "Entities are `schema__table`. Solid lines are foreign keys; dotted lines are relationships kept by",
        "triggers or by the application (no foreign key). Only key, relationship and geometry columns are",
        "shown; [SCHEMA.md](SCHEMA.md) lists every column.",
        "",
        "```mermaid",
        "erDiagram",
    ]
    for t in tables:
        key_columns = {col for c in t.constraints if c.kind in ("p", "f") for col in c.columns}
        primary = {col for c in t.constraints if c.kind == "p" for col in c.columns}
        foreign = {col for c in t.constraints if c.kind == "f" for col in c.columns}
        lines.append(f"    {entity(t.qualified)} {{")
        for column in t.columns:
            is_geometry = column.type.startswith("geometry")
            if column.name not in key_columns and not is_geometry and column.name not in {"code", "name"}:
                continue
            marks = ",".join(m for m, s in (("PK", primary), ("FK", foreign)) if column.name in s)
            kind = column.type.split("(")[0].replace(" ", "_")
            detail = column.type[len("geometry") :].strip("()") if is_geometry else ""
            comment = f' "{detail}"' if detail else ""
            lines.append(f"        {kind} {column.name}{(' ' + marks) if marks else ''}{comment}")
        lines.append("    }")
    edges: dict[tuple[str, str], list[str]] = defaultdict(list)
    optional: dict[tuple[str, str], bool] = {}
    for t in tables:
        not_null = {c.name for c in t.columns if c.not_null}
        for c in t.constraints:
            if c.kind != "f" or c.referenced is None:
                continue
            key = (c.referenced, t.qualified)
            edges[key].append(", ".join(c.columns))
            optional[key] = optional.get(key, False) or not all(col in not_null for col in c.columns)
    for (parent, child), labels in sorted(edges.items()):
        left = "|o" if optional[(parent, child)] else "||"
        lines.append(f'    {entity(parent)} {left}--o{{ {entity(child)} : "{"; ".join(sorted(set(labels)))}"')
    for child, parent, columns, label in LOGICAL_LINKS:
        lines.append(f'    {entity(parent)} |o..o{{ {entity(child)} : "{columns}: {label}"')
    lines += ["```", ""]
    return "\n".join(lines)


async def generate() -> dict[Path, str]:
    settings = get_settings()
    engine = create_engine(settings, DbRole.MIGRATOR)
    try:
        async with engine.connect() as connection:
            model = await load(connection)
    finally:
        await engine.dispose()
    return {OUTPUT_DIR / "SCHEMA.md": schema_markdown(model), OUTPUT_DIR / "ERD.md": erd_markdown(model)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the documents are out of date")
    args = parser.parse_args()
    documents = asyncio.run(generate())
    stale = [path for path, content in documents.items() if not path.exists() or path.read_text() != content]
    if args.check:
        for path in stale:
            print(f"out of date: {path.relative_to(REPOSITORY_ROOT)}", file=sys.stderr)
        return 1 if stale else 0
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, content in documents.items():
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
