"""Event locations and geo-context (schema ``geo``).

* ``geo.event_location``      where and when an event was observed: point, line or area geometry, how
                              the location was obtained, optional device and field-of-view snapshot
* ``geo.event_geo_context``   the geographic context computed for an event (admin hierarchy, nearest
                              settlement and road, zones, geofence hits, nearest devices) with the
                              reference data release it was computed against
* ``geo.event_zone_hit``      protected areas and risk zones the event location falls in
* ``geo.event_geofence_hit``  geofences the event location falls in

All four tables are partitioned by month of ``observed_at`` (UTC). Partitions are named
``<table>_pYYYYMM``. There is no default partition, so an event outside the prepared months fails loudly
instead of piling up in a catch-all table:

* ``geo.prepare_event_partitions(from, to)`` (migration login, e.g. from a monthly job or before a
  historical import) creates the partitions of a range of months;
* ``geo.ensure_event_partition(observed_at)`` (runtime login) creates the month on demand, but only for
  recent observations (13 months back to 1 day ahead), so a client cannot trigger mass table creation.

Rows are visible only to the owning tenant (row-level security on the partitioned tables; direct access
to partitions is denied to the runtime login). Geofence hits are snapshots (geofence id, owner, version):
they do not pin the geofence, which may belong to another tenant that shared it.

The GIS service records spatial facts only. Nothing here selects recipients or sends notifications.

Revision ID: 20260915_0005
Revises: 20260915_0004
Create Date: 2026-09-15 00:00:04+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from migration_support import (
    app_role,
    comment_columns,
    comment_table,
    geometry_checks,
    gist_index,
    metric_twin,
    refuse_if_not_empty,
    register_layer,
    tenant_policies,
    touch_trigger,
    unregister_layers,
)

revision: str = "20260915_0005"
down_revision: str | Sequence[str] | None = "20260915_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARTITIONED_TABLES = ("event_location", "event_geo_context", "event_zone_hit", "event_geofence_hit")
OWN_TENANT = "tenant_id = meta.current_tenant_id()"
EVENT_GEOMETRY_TYPES = ("POINT", "LINESTRING", "POLYGON", "MULTIPOINT", "MULTILINESTRING", "MULTIPOLYGON")
GEO_CONTEXT_KEYS = (
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
# Oldest month that can be prepared (historical imports).
EVENT_HISTORY_START = "2000-01-01 00:00:00+00"
# Months the runtime login may create on demand, relative to now().
ON_DEMAND_PAST = "13 months"
ON_DEMAND_FUTURE = "1 day"
# How far observed_at may lie after received_at (clock skew between sources and the service).
CLOCK_SKEW = "1 day"


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _event_location() -> None:
    op.execute(
        f"""
        CREATE TABLE geo.event_location (
            tenant_id text NOT NULL DEFAULT meta.current_tenant_id(),
            event_id text NOT NULL,
            observed_at timestamptz NOT NULL,
            event_type text NOT NULL,
            event_subtype text,
            source_type text NOT NULL,
            device_id uuid,
            source_ref text,
            location_source text NOT NULL,
            geom public.geometry(Geometry, 4326) NOT NULL,
            {metric_twin("geom", "Geometry")},
            geometry_kind text GENERATED ALWAYS AS (
                CASE public.ST_Dimension(geom) WHEN 0 THEN 'point' WHEN 1 THEN 'line' ELSE 'area' END
            ) STORED,
            location_accuracy_m numeric(10, 2),
            field_of_view_id uuid,
            field_of_view public.geometry(MultiPolygon, 4326),
            attributes jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            received_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_event_location PRIMARY KEY (tenant_id, event_id, observed_at),
            CONSTRAINT fk_event_location_tenant_id_tenant FOREIGN KEY (tenant_id)
                REFERENCES meta.tenant (tenant_id) ON DELETE RESTRICT,
            CONSTRAINT fk_event_location_device_id_tenant_id_device FOREIGN KEY (device_id, tenant_id)
                REFERENCES ops.device (id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT fk_event_location_field_of_view_id_tenant_id_device_field_of_view
                FOREIGN KEY (field_of_view_id, tenant_id)
                REFERENCES ops.device_field_of_view (id, tenant_id) ON DELETE RESTRICT,
            CONSTRAINT ck_event_location_event_id_format
                CHECK (event_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{{0,127}}$'),
            CONSTRAINT ck_event_location_event_type_format
                CHECK (event_type ~ '^[a-z][a-z0-9_]*([.][a-z][a-z0-9_]*)*$' AND length(event_type) <= 100),
            CONSTRAINT ck_event_location_source_type
                CHECK (source_type IN ('device', 'sensor', 'external', 'manual')),
            CONSTRAINT ck_event_location_location_source
                CHECK (location_source IN ('device', 'estimated', 'sensor', 'external')),
            CONSTRAINT ck_event_location_geometry_type
                CHECK (public.GeometryType(geom) IN ({_in(EVENT_GEOMETRY_TYPES)})),
            CONSTRAINT ck_event_location_location_accuracy_m CHECK (location_accuracy_m > 0),
            CONSTRAINT ck_event_location_attributes_is_object CHECK (jsonb_typeof(attributes) = 'object'),
            CONSTRAINT ck_event_location_observed_at_finite CHECK (isfinite(observed_at)),
            CONSTRAINT ck_event_location_observed_at_not_future
                CHECK (observed_at <= received_at + interval '{CLOCK_SKEW}'),
            {geometry_checks("geo.event_location")},
            {geometry_checks("geo.event_location", "field_of_view", nullable=True)}
        ) PARTITION BY RANGE (observed_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_event_location_tenant_id_observed_at ON geo.event_location (tenant_id, observed_at)"
    )
    op.execute(
        "CREATE INDEX ix_event_location_tenant_id_event_type_observed_at "
        "ON geo.event_location (tenant_id, event_type, observed_at)"
    )
    op.execute(
        "CREATE INDEX ix_event_location_device_id_observed_at ON geo.event_location (device_id, observed_at) "
        "WHERE device_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_event_location_field_of_view_id ON geo.event_location (field_of_view_id) "
        "WHERE field_of_view_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX ix_event_location_observed_at_brin ON geo.event_location USING brin (observed_at)"
    )
    gist_index("geo.event_location", "geom")
    gist_index("geo.event_location", "geom_metric")
    touch_trigger("geo.event_location")
    comment_table(
        "geo.event_location",
        "Observed location of an event (point, line or area), partitioned by month of observed_at (UTC).",
    )
    comment_columns(
        "geo.event_location",
        {
            "tenant_id": "Tenant that owns the event.",
            "event_id": "Event identifier assigned by the event platform.",
            "observed_at": "When the event was observed. Partition key.",
            "event_type": "Dotted lower-case event type, e.g. wildlife.elephant_detected.",
            "source_type": "device, sensor, external or manual.",
            "device_id": "Device that observed the event (same tenant).",
            "source_ref": "Identifier of the source in an external system.",
            "location_source": "device (installed position of the device), estimated (computed, e.g. "
            "triangulated), sensor (position reported by the sensor, e.g. GNSS) or external.",
            "geom": "Event geometry, EPSG:4326: point, line or area.",
            "geom_metric": "Stored EPSG:5235 copy of geom.",
            "geometry_kind": "point, line or area, from the dimension of geom.",
            "location_accuracy_m": "Estimated horizontal accuracy of the location in metres.",
            "field_of_view_id": "Device field of view in effect when the event was observed.",
            "field_of_view": "Snapshot of the field-of-view area at observation time, EPSG:4326.",
            "attributes": "Additional GIS-relevant event metadata (JSON object).",
            "received_at": "When the GIS service stored the event location.",
        },
    )


def _event_geo_context() -> None:
    required = "ARRAY[" + _in(GEO_CONTEXT_KEYS) + "]"
    op.execute(
        f"""
        CREATE TABLE geo.event_geo_context (
            tenant_id text NOT NULL,
            event_id text NOT NULL,
            observed_at timestamptz NOT NULL,
            schema_version text NOT NULL DEFAULT 'geo-context/1',
            release_id uuid NOT NULL,
            release_code text NOT NULL,
            computed_at timestamptz NOT NULL DEFAULT now(),
            location_source text NOT NULL,
            admin_l1_id uuid,
            admin_l1_code text,
            admin_l2_id uuid,
            admin_l2_code text,
            admin_l3_id uuid,
            admin_l3_code text,
            admin_l4_id uuid,
            admin_l4_code text,
            nearest_settlement_id uuid,
            nearest_settlement_distance_m numeric(12, 2),
            nearest_road_id uuid,
            nearest_road_distance_m numeric(12, 2),
            document jsonb NOT NULL,
            CONSTRAINT pk_event_geo_context PRIMARY KEY (tenant_id, event_id, observed_at),
            CONSTRAINT fk_event_geo_context_tenant_id_event_id_observed_at_event_location
                FOREIGN KEY (tenant_id, event_id, observed_at)
                REFERENCES geo.event_location (tenant_id, event_id, observed_at) ON DELETE CASCADE,
            CONSTRAINT fk_event_geo_context_release_id_ref_data_release FOREIGN KEY (release_id)
                REFERENCES meta.ref_data_release (id) ON DELETE RESTRICT,
            CONSTRAINT ck_event_geo_context_schema_version CHECK (schema_version ~ '^geo-context/[0-9]+$'),
            CONSTRAINT ck_event_geo_context_document CHECK (
                jsonb_typeof(document) = 'object'
                AND document ?& {required}
                AND document ->> 'schemaVersion' = schema_version
            ),
            CONSTRAINT ck_event_geo_context_distances CHECK (
                nearest_settlement_distance_m >= 0 AND nearest_road_distance_m >= 0
            ),
            CONSTRAINT ck_event_geo_context_location_source
                CHECK (location_source IN ('device', 'estimated', 'sensor', 'external'))
        ) PARTITION BY RANGE (observed_at)
        """
    )
    op.execute("CREATE INDEX ix_event_geo_context_release_id ON geo.event_geo_context (release_id)")
    op.execute(
        "CREATE INDEX ix_event_geo_context_tenant_id_admin_l2_id_observed_at "
        "ON geo.event_geo_context (tenant_id, admin_l2_id, observed_at)"
    )
    comment_table(
        "geo.event_geo_context",
        "Geographic context of an event, computed against one reference data release. The full result "
        "is in document (schema geo-context/1); frequently filtered values are also columns.",
    )
    comment_columns(
        "geo.event_geo_context",
        {
            "schema_version": "Version of the geo-context document schema.",
            "release_id": "Reference data release the context was computed against.",
            "release_code": "Code of that release (ref-YYYY.MM).",
            "computed_at": "When the context was computed.",
            "admin_l1_id": "Province containing the event (ref.admin_area, level 1).",
            "admin_l2_id": "District containing the event (level 2).",
            "admin_l3_id": "DS division containing the event (level 3).",
            "admin_l4_id": "GN division containing the event (level 4).",
            "nearest_settlement_distance_m": "Distance to the nearest settlement in metres (EPSG:5235).",
            "nearest_road_distance_m": "Distance to the nearest road in metres (EPSG:5235).",
            "document": "Complete geo-context as returned by the API (camelCase JSON).",
        },
    )


def _hits() -> None:
    op.execute(
        """
        CREATE TABLE geo.event_zone_hit (
            tenant_id text NOT NULL,
            event_id text NOT NULL,
            observed_at timestamptz NOT NULL,
            zone_kind text NOT NULL,
            zone_id uuid NOT NULL,
            relation text NOT NULL,
            CONSTRAINT pk_event_zone_hit PRIMARY KEY (tenant_id, event_id, observed_at, zone_kind, zone_id),
            CONSTRAINT fk_event_zone_hit_tenant_id_event_id_observed_at_event_geo_context
                FOREIGN KEY (tenant_id, event_id, observed_at)
                REFERENCES geo.event_geo_context (tenant_id, event_id, observed_at) ON DELETE CASCADE,
            CONSTRAINT ck_event_zone_hit_zone_kind CHECK (zone_kind IN ('protected_area', 'risk_zone')),
            CONSTRAINT ck_event_zone_hit_relation CHECK (relation IN ('within', 'intersects'))
        ) PARTITION BY RANGE (observed_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_event_zone_hit_zone_id_observed_at ON geo.event_zone_hit (zone_id, observed_at)"
    )
    comment_table(
        "geo.event_zone_hit",
        "Protected areas and risk zones an event lies in (within) or overlaps (intersects).",
    )
    comment_columns(
        "geo.event_zone_hit",
        {
            "zone_kind": "protected_area or risk_zone (table in schema ref).",
            "zone_id": "id of the zone row, in the release of the geo-context.",
            "relation": "within: the event geometry lies in the zone (boundary included); "
            "intersects: it overlaps the zone partly.",
        },
    )

    op.execute(
        """
        CREATE TABLE geo.event_geofence_hit (
            tenant_id text NOT NULL,
            event_id text NOT NULL,
            observed_at timestamptz NOT NULL,
            geofence_id uuid NOT NULL,
            geofence_tenant_id text NOT NULL,
            geofence_version integer NOT NULL,
            relation text NOT NULL,
            CONSTRAINT pk_event_geofence_hit PRIMARY KEY (tenant_id, event_id, observed_at, geofence_id),
            CONSTRAINT fk_event_geofence_hit_tenant_id_event_id_observed_at_event_geo_context
                FOREIGN KEY (tenant_id, event_id, observed_at)
                REFERENCES geo.event_geo_context (tenant_id, event_id, observed_at) ON DELETE CASCADE,
            CONSTRAINT ck_event_geofence_hit_geofence_version CHECK (geofence_version >= 1),
            CONSTRAINT ck_event_geofence_hit_relation CHECK (relation IN ('within', 'intersects'))
        ) PARTITION BY RANGE (observed_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_event_geofence_hit_geofence_id_observed_at "
        "ON geo.event_geofence_hit (geofence_id, observed_at)"
    )
    comment_table(
        "geo.event_geofence_hit",
        "Geofences an event lies in, as a snapshot: the hit keeps the geofence id, owner and version even "
        "if the geofence is later changed or deleted. No foreign key, so a hit never pins a geofence that "
        "another tenant shared.",
    )
    comment_columns(
        "geo.event_geofence_hit",
        {
            "geofence_id": "id of the ops.geofence row at computation time.",
            "geofence_tenant_id": "Owner of the geofence (may differ from tenant_id for shared geofences).",
            "geofence_version": "Version of the geofence the hit was computed against.",
            "relation": "within: the whole event lies in the geofence (for circles and corridors: inside the "
            "buffer of radius_m drawn with 32 segments per quarter circle; a point hit is always within); "
            "intersects: only part of it does.",
        },
    )


def _partition_functions() -> None:
    parents = "ARRAY[" + _in(PARTITIONED_TABLES) + "]"
    # Worker: creates the four partitions of one month. Owner only (not granted to the runtime login).
    op.execute(
        f"""
        CREATE FUNCTION geo.create_event_partitions(p_month timestamptz)
        RETURNS text
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        SET TimeZone = 'UTC'
        AS $$
        DECLARE
            month_start timestamptz;
            month_end timestamptz;
            suffix text;
            parent text;
            partition_name text;
        BEGIN
            IF p_month IS NULL OR NOT isfinite(p_month) THEN
                RAISE EXCEPTION 'the month must be a finite timestamp' USING ERRCODE = '22023';
            END IF;
            IF p_month < timestamptz '{EVENT_HISTORY_START}' OR p_month > now() + interval '13 months' THEN
                RAISE EXCEPTION 'event partitions can be prepared from % to 13 months ahead, not for %',
                    '{EVENT_HISTORY_START[:10]}', p_month USING ERRCODE = '22023';
            END IF;
            month_start := date_trunc('month', p_month);
            month_end := month_start + interval '1 month';
            suffix := to_char(month_start, 'YYYYMM');

            FOREACH parent IN ARRAY {parents} LOOP
                partition_name := parent || '_p' || suffix;
                IF to_regclass(format('geo.%I', partition_name)) IS NULL THEN
                    PERFORM pg_advisory_xact_lock(hashtext('geo.create_event_partitions'));
                    IF to_regclass(format('geo.%I', partition_name)) IS NULL THEN
                        EXECUTE format(
                            'CREATE TABLE geo.%I PARTITION OF geo.%I FOR VALUES FROM (%L) TO (%L)',
                            partition_name, parent, month_start, month_end);
                        -- No policies: the runtime login reaches rows only through the partitioned table.
                        EXECUTE format('ALTER TABLE geo.%I ENABLE ROW LEVEL SECURITY', partition_name);
                        EXECUTE format(
                            'COMMENT ON TABLE geo.%I IS %L', partition_name,
                            format('Partition of geo.%s for %s (UTC).',
                                   parent, to_char(month_start, 'YYYY-MM')));
                    END IF;
                END IF;
            END LOOP;
            RETURN suffix;
        END
        $$
        """
    )
    # Operators: a range of months (monthly job, historical imports).
    op.execute(
        """
        CREATE FUNCTION geo.prepare_event_partitions(p_from timestamptz, p_to timestamptz)
        RETURNS SETOF text
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        SET TimeZone = 'UTC'
        AS $$
        DECLARE
            month_start timestamptz := date_trunc('month', p_from);
        BEGIN
            IF p_to < p_from THEN
                RAISE EXCEPTION 'the range ends before it starts' USING ERRCODE = '22023';
            END IF;
            WHILE month_start <= p_to LOOP
                RETURN NEXT geo.create_event_partitions(month_start);
                month_start := month_start + interval '1 month';
            END LOOP;
        END
        $$
        """
    )
    # Runtime login: on demand, for recent observations only.
    op.execute(
        f"""
        CREATE FUNCTION geo.ensure_event_partition(p_observed_at timestamptz)
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        SET TimeZone = 'UTC'
        AS $$
        BEGIN
            IF p_observed_at IS NULL OR NOT isfinite(p_observed_at) THEN
                RAISE EXCEPTION 'observed_at must be a finite timestamp' USING ERRCODE = '22023';
            END IF;
            IF p_observed_at < now() - interval '{ON_DEMAND_PAST}'
                OR p_observed_at > now() + interval '{ON_DEMAND_FUTURE}' THEN
                RAISE EXCEPTION 'observed_at % is outside the on-demand window (now - % to now + %)',
                    p_observed_at, '{ON_DEMAND_PAST}', '{ON_DEMAND_FUTURE}'
                    USING ERRCODE = '22023',
                          HINT = 'Operators prepare other months: geo.prepare_event_partitions(from, to).';
            END IF;
            RETURN geo.create_event_partitions(p_observed_at);
        END
        $$
        """
    )
    op.execute(
        "COMMENT ON FUNCTION geo.create_event_partitions(timestamptz) IS "
        "'Create the four monthly partitions of the geo event tables for the month (UTC) containing the "
        "given time, if missing; returns the suffix YYYYMM. Owner only.'"
    )
    op.execute(
        "COMMENT ON FUNCTION geo.prepare_event_partitions(timestamptz, timestamptz) IS "
        "'Create the event partitions of every month (UTC) from p_from to p_to. Owner only; for a monthly "
        "job and before historical imports.'"
    )
    op.execute(
        "COMMENT ON FUNCTION geo.ensure_event_partition(timestamptz) IS "
        f"'Create the event partitions of the month containing a recent observation (now - {ON_DEMAND_PAST} "
        f"to now + {ON_DEMAND_FUTURE}). Security definer; granted to the runtime login.'"
    )
    role = app_role()
    for signature in (
        "create_event_partitions(timestamptz)",
        "prepare_event_partitions(timestamptz, timestamptz)",
        "ensure_event_partition(timestamptz)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION geo.{signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION geo.ensure_event_partition(timestamptz) TO {role}")


def upgrade() -> None:
    _event_location()
    _event_geo_context()
    _hits()
    for table in PARTITIONED_TABLES:
        tenant_policies(f"geo.{table}", OWN_TENANT)
    _partition_functions()
    # Previous, current and next month (UTC).
    op.execute("SELECT geo.prepare_event_partitions(now() - interval '1 month', now() + interval '1 month')")
    register_layer(
        code="geo.event_location",
        name="Event locations",
        description="Observed locations of events (points, lines and areas).",
        layer_group="event",
        geometry_types=EVENT_GEOMETRY_TYPES,
        tenant_scoped=True,
        default_sharing_policy=None,
        update_frequency="continuous",
        nominal_accuracy_m=None,
    )


def downgrade() -> None:
    refuse_if_not_empty([f"geo.{table}" for table in PARTITIONED_TABLES])
    unregister_layers(["geo.event_location"])
    op.execute("DROP FUNCTION geo.ensure_event_partition(timestamptz)")
    op.execute("DROP FUNCTION geo.prepare_event_partitions(timestamptz, timestamptz)")
    op.execute("DROP FUNCTION geo.create_event_partitions(timestamptz)")
    # Dropping a partitioned table drops its partitions.
    for table in reversed(PARTITIONED_TABLES):
        op.execute(f"DROP TABLE geo.{table}")
