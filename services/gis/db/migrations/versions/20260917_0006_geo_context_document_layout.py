"""Geo-context document layout of the enrichment API (``geo-context/1``, plan §5.3).

The enrichment endpoint returns the block proposed in plan §5.3: ``schema``, ``insideZones`` and
``refDataRelease`` (the release code, which is unique), plus the members the engine adds (``tenantId``,
``admin.codes``, ``missingLayers``, ``inFieldOfView`` of nearby devices). This revision

* replaces ``ck_event_geo_context_document`` with the new required members and ties the document to
  its row (``schema``, ``eventId``, ``tenantId`` and ``refDataRelease`` must equal the columns);
* converts stored documents from the pre-release layout (``schemaVersion``, ``zones``,
  ``referenceDataRelease``). Values the old layout did not have are derived: ``admin.codes`` from the
  admin code columns, ``missingLayers`` from the release's load records, ``inFieldOfView`` is null
  (unknown).

The downgrade converts documents back; the members the old layout has no place for (``tenantId``,
``admin.codes``, ``missingLayers``, ``inFieldOfView``) are derived values and are dropped. Row data is
never deleted.

Revision ID: 20260917_0006
Revises: 20260915_0005
Create Date: 2026-09-17 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0006"
down_revision: str | Sequence[str] | None = "20260915_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_event_geo_context_document"
GEO_CONTEXT_KEYS = (
    "schema",
    "eventId",
    "tenantId",
    "observedAt",
    "locationSource",
    "geometryKind",
    "admin",
    "nearestSettlement",
    "nearestRoad",
    "insideZones",
    "geofenceHits",
    "nearestDevices",
    "missingLayers",
    "search",
    "refDataRelease",
    "computedAt",
)
ARRAY_KEYS = ("insideZones", "geofenceHits", "nearestDevices", "missingLayers")
# Layout of revision 20260915_0005 (restored by the downgrade).
PREVIOUS_GEO_CONTEXT_KEYS = (
    "schemaVersion",
    "eventId",
    "observedAt",
    "locationSource",
    "referenceDataRelease",
    "computedAt",
    "admin",
    "nearestSettlement",
    "nearestRoad",
    "zones",
    "geofenceHits",
    "nearestDevices",
)
# Order of missingLayers (app.schemas.geo_context.CONTEXT_REFERENCE_LAYERS); the VALUES list in
# UPGRADE_DOCUMENTS follows it.
CONTEXT_REFERENCE_LAYERS = ("admin_area", "settlement", "road", "protected_area", "risk_zone")


def _array(values: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{value}'" for value in values) + "]"


def _document_check() -> str:
    arrays = " AND ".join(f"jsonb_typeof(document -> '{key}') = 'array'" for key in ARRAY_KEYS)
    return (
        f"jsonb_typeof(document) = 'object' "
        f"AND document ?& {_array(GEO_CONTEXT_KEYS)} "
        f"AND document ->> 'schema' = schema_version "
        f"AND document ->> 'eventId' = event_id "
        f"AND document ->> 'tenantId' = tenant_id "
        f"AND document ->> 'refDataRelease' = release_code "
        f"AND jsonb_typeof(document -> 'admin') = 'object' "
        f"AND {arrays}"
    )


def _previous_document_check() -> str:
    return (
        f"jsonb_typeof(document) = 'object' "
        f"AND document ?& {_array(PREVIOUS_GEO_CONTEXT_KEYS)} "
        f"AND document ->> 'schemaVersion' = schema_version"
    )


def _create_conversion_functions() -> None:
    # Session-local helpers; dropped again below.
    op.execute(
        """
        CREATE FUNCTION pg_temp.gis_rename_keys(obj jsonb, mapping jsonb, drop_keys text[])
        RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
            SELECT CASE WHEN jsonb_typeof(obj) = 'object' THEN (
                SELECT coalesce(jsonb_object_agg(coalesce(mapping ->> e.key, e.key), e.value), '{}'::jsonb)
                FROM jsonb_each(obj) AS e
                WHERE NOT e.key = ANY (drop_keys)
            ) ELSE obj END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION pg_temp.gis_convert_items(items jsonb, mapping jsonb, drop_keys text[], extra jsonb)
        RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
            SELECT coalesce(
                jsonb_agg(pg_temp.gis_rename_keys(t.item, mapping, drop_keys) || extra ORDER BY t.ord),
                '[]'::jsonb
            )
            FROM jsonb_array_elements(coalesce(items, '[]'::jsonb)) WITH ORDINALITY AS t(item, ord)
        $$
        """
    )


def _drop_conversion_functions() -> None:
    op.execute("DROP FUNCTION pg_temp.gis_convert_items(jsonb, jsonb, text[], jsonb)")
    op.execute("DROP FUNCTION pg_temp.gis_rename_keys(jsonb, jsonb, text[])")


# Old layout -> new layout. The UPDATE is a constant; it converts only documents in the old layout.
UPGRADE_DOCUMENTS = """
UPDATE geo.event_geo_context AS c
SET document = jsonb_build_object(
    'schema', c.document -> 'schemaVersion',
    'eventId', c.document -> 'eventId',
    'tenantId', to_jsonb(c.tenant_id),
    'observedAt', c.document -> 'observedAt',
    'locationSource', c.document -> 'locationSource',
    'geometryKind', c.document -> 'geometryKind',
    'admin', (c.document -> 'admin') || jsonb_build_object('codes', jsonb_build_object(
        'l1', c.admin_l1_code, 'l2', c.admin_l2_code, 'l3', c.admin_l3_code, 'l4', c.admin_l4_code
    )),
    'nearestSettlement', pg_temp.gis_rename_keys(
        c.document -> 'nearestSettlement', '{"geometryBasis": "basis"}', '{}'
    ),
    'nearestRoad', pg_temp.gis_rename_keys(c.document -> 'nearestRoad', '{"roadClass": "class"}', '{}'),
    'insideZones', pg_temp.gis_convert_items(c.document -> 'zones', '{"kind": "type"}', '{}', '{}'),
    'geofenceHits', pg_temp.gis_convert_items(
        c.document -> 'geofenceHits',
        '{"geofenceKind": "kind", "ownerTenantId": "tenantId"}', '{}', '{}'
    ),
    'nearestDevices', pg_temp.gis_convert_items(
        c.document -> 'nearestDevices',
        '{"id": "deviceId", "ownerTenantId": "tenantId"}', '{}', '{"inFieldOfView": null}'
    ),
    'missingLayers', (
        SELECT coalesce(jsonb_agg(l.name ORDER BY l.ord), '[]'::jsonb)
        FROM (VALUES
            (1, 'admin_area', 'ref.admin_area'),
            (2, 'settlement', 'ref.settlement'),
            (3, 'road', 'ref.road'),
            (4, 'protected_area', 'ref.protected_area'),
            (5, 'risk_zone', 'ref.risk_zone')
        ) AS l(ord, name, layer_code)
        WHERE NOT EXISTS (
            SELECT 1 FROM meta.dataset_load AS d JOIN meta.layer AS y ON y.id = d.layer_id
            WHERE d.release_id = c.release_id AND y.code = l.layer_code
              AND d.status = 'completed' AND d.loaded_count > 0
        )
    ),
    'search', c.document -> 'search',
    'refDataRelease', to_jsonb(c.release_code),
    'computedAt', c.document -> 'computedAt'
)
WHERE c.document ? 'schemaVersion'
"""

# New layout -> old layout.
DOWNGRADE_DOCUMENTS = """
UPDATE geo.event_geo_context AS c
SET document = jsonb_build_object(
    'schemaVersion', c.document -> 'schema',
    'eventId', c.document -> 'eventId',
    'observedAt', c.document -> 'observedAt',
    'locationSource', c.document -> 'locationSource',
    'geometryKind', c.document -> 'geometryKind',
    'referenceDataRelease', jsonb_build_object('id', c.release_id, 'code', c.release_code),
    'computedAt', c.document -> 'computedAt',
    'admin', (c.document -> 'admin') - 'codes',
    'nearestSettlement', pg_temp.gis_rename_keys(
        c.document -> 'nearestSettlement', '{"basis": "geometryBasis"}', '{}'
    ),
    'nearestRoad', pg_temp.gis_rename_keys(c.document -> 'nearestRoad', '{"class": "roadClass"}', '{}'),
    'zones', pg_temp.gis_convert_items(c.document -> 'insideZones', '{"type": "kind"}', '{}', '{}'),
    'geofenceHits', pg_temp.gis_convert_items(
        c.document -> 'geofenceHits',
        '{"kind": "geofenceKind", "tenantId": "ownerTenantId"}', '{}', '{}'
    ),
    'nearestDevices', pg_temp.gis_convert_items(
        c.document -> 'nearestDevices',
        '{"deviceId": "id", "tenantId": "ownerTenantId"}', '{inFieldOfView}', '{}'
    ),
    'search', c.document -> 'search'
)
WHERE c.document ? 'schema'
"""


def _replace_documents(conversion: str, check: str) -> None:
    op.execute(f"ALTER TABLE geo.event_geo_context DROP CONSTRAINT {CONSTRAINT}")
    _create_conversion_functions()
    op.execute(conversion)
    _drop_conversion_functions()
    op.execute(f"ALTER TABLE geo.event_geo_context ADD CONSTRAINT {CONSTRAINT} CHECK ({check})")


def upgrade() -> None:
    _replace_documents(UPGRADE_DOCUMENTS, _document_check())


def downgrade() -> None:
    _replace_documents(DOWNGRADE_DOCUMENTS, _previous_document_check())
