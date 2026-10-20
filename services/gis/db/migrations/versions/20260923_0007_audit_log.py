"""Audit log (schema ``audit``): who searched, queried, exported and changed what, and roughly where.

``audit.entry`` holds one row per audited operation (plan §9, ADR-0017):

* **searches** and **sensitive queries** (every read of tenant operational data and events) and
  **exports** are recorded by the API in the same transaction as the read, so an answer is never given
  without its record;
* **changes** to geofences, sites and device placements, and the lifecycle of **reference data
  releases**, are recorded by triggers on ``ops.geofence``, ``ops.site``, ``ops.device`` and
  ``meta.ref_data_release``, so no code path - the API, the loader or a login changing rows directly -
  can change them without a record.

Who and when is **stamped by the database**, not supplied by the writer: a BEFORE INSERT trigger sets
the time, the tenant (``meta.current_tenant_id()``), the actor, client, roles, request id and channel
from the transaction-local context the API writes next to the tenant (``gis.actor_subject``,
``gis.actor_client``, ``gis.actor_roles``, ``gis.request_id``, ``gis.channel``, ``gis.cross_tenant``) and
the database login. Without that context (a login changing data directly) the login is the actor, the
channel is ``database``, and a change is filed under the changed row's tenant, so the owning tenant sees
it in its log. (A writer without a tenant cannot use this to file entries for a tenant: the insert policy
requires the entry's tenant to be the transaction's.)

Append-only: the runtime login has INSERT and SELECT only, and triggers refuse UPDATE, DELETE and
TRUNCATE for every login - retention is an explicit administrative act (disable the triggers, delete,
re-enable). Row-level security: a tenant reads and writes only its own entries; entries without a
tenant (reference data releases, searches by services acting for no tenant) are visible only to
transactions without a tenant.

Privacy: geometry is recorded as its type and a coarse extent - the bounding box widened to a 0.001
degree grid (about 110 m) - never the geometry itself. A search around a point may be a search around a
person; the log keeps enough to investigate its own use, not a copy of every location asked about. The
actor is the identity provider's opaque subject id, never a name or an e-mail address.

Revision ID: 20260923_0007
Revises: 20260917_0006
Create Date: 2026-09-23 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from migration_support import app_role, comment_columns, comment_table, refuse_if_not_empty

revision: str = "20260923_0007"
down_revision: str | Sequence[str] | None = "20260917_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ID_PATTERN = "^[a-z0-9][a-z0-9_-]{1,62}$"
OPERATION_PATTERN = "^[a-z][a-z_]*([.][a-z][a-z_]*)+$"
CATEGORIES = ("search", "sensitive_query", "export", "change", "release")
CHANNELS = ("api", "loader", "database")
# Operational tables whose changes are audited: (table, subject, retired status, retiring verb).
AUDITED_OPERATIONAL_TABLES = (
    ("ops.geofence", "geofence", "archived", "archive"),
    ("ops.site", "site", "decommissioned", "decommission"),
    ("ops.device", "device", "decommissioned", "decommission"),
)


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _table() -> None:
    op.execute(
        f"""
        CREATE TABLE audit.entry (
            id bigint GENERATED ALWAYS AS IDENTITY,
            occurred_at timestamptz NOT NULL,
            tenant_id text,
            category text NOT NULL,
            operation text NOT NULL,
            target text,
            object_id text,
            actor_subject text NOT NULL,
            actor_client text,
            actor_roles text[] NOT NULL,
            cross_tenant boolean NOT NULL,
            channel text NOT NULL,
            request_id text,
            db_user text NOT NULL,
            geometry_type text,
            geometry_extent public.geometry(Polygon, 4326),
            parameters jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            result_count integer,
            CONSTRAINT pk_entry PRIMARY KEY (id),
            CONSTRAINT ck_entry_tenant_id_format CHECK (tenant_id ~ '{TENANT_ID_PATTERN}'),
            CONSTRAINT ck_entry_category CHECK (category IN {_in(CATEGORIES)}),
            CONSTRAINT ck_entry_operation_format CHECK (operation ~ '{OPERATION_PATTERN}'),
            CONSTRAINT ck_entry_channel CHECK (channel IN {_in(CHANNELS)}),
            CONSTRAINT ck_entry_actor_subject_not_blank CHECK (btrim(actor_subject) <> ''),
            CONSTRAINT ck_entry_cross_tenant_names_tenant CHECK (NOT cross_tenant OR tenant_id IS NOT NULL),
            CONSTRAINT ck_entry_parameters_is_object CHECK (jsonb_typeof(parameters) = 'object'),
            CONSTRAINT ck_entry_result_count CHECK (result_count >= 0),
            CONSTRAINT ck_entry_geometry_extent_valid CHECK (public.ST_IsValid(geometry_extent, 0))
        )
        """
    )
    # Keyset paging of one tenant's log, newest first; what one actor did; retention by time; and
    # "who asked about this area" for an investigation of the log itself.
    op.execute("CREATE INDEX ix_entry_tenant_id_occurred_at_id ON audit.entry (tenant_id, occurred_at, id)")
    op.execute("CREATE INDEX ix_entry_actor_subject_occurred_at ON audit.entry (actor_subject, occurred_at)")
    op.execute("CREATE INDEX ix_entry_occurred_at_brin ON audit.entry USING brin (occurred_at)")
    op.execute("CREATE INDEX ix_entry_geometry_extent_gist ON audit.entry USING gist (geometry_extent)")
    comment_table(
        "audit.entry",
        "Append-only audit log: searches, sensitive queries and exports (recorded by the API in the "
        "transaction that answers them) and changes to geofences, sites, devices and reference data "
        "releases (recorded by triggers). Who, when and for which tenant is stamped by the database.",
    )
    comment_columns(
        "audit.entry",
        {
            "occurred_at": "When the operation ran (clock time, stamped by the database).",
            "tenant_id": "Tenant the operation acted for: the transaction's tenant, stamped by the "
            "database; for a change made without one (directly in the database), the changed row's "
            "tenant. NULL for reference data releases and requests acting for no tenant.",
            "category": "search, sensitive_query (a read of tenant operational data or events), export, "
            "change (geofence, site, device) or release (reference data).",
            "operation": "What was done, e.g. query.within_distance, events.list, geofence.archive, "
            "reference_release.publish.",
            "target": "Layer or table the operation read or changed.",
            "object_id": "Identifier of the object changed or read, when there is one.",
            "actor_subject": "Opaque subject id of the caller from the identity provider (never a name "
            "or e-mail address); the database login when no caller context was set.",
            "actor_client": "OAuth client the caller used (azp).",
            "actor_roles": "GIS roles the caller held.",
            "cross_tenant": "True when a platform role or service acted for a tenant that is not its own.",
            "channel": "api, loader (reference data tool) or database (a login changing rows directly).",
            "request_id": "Request id of the API call (also in the access log).",
            "db_user": "Database login that wrote the entry.",
            "geometry_type": "Type of the geometry searched with or changed.",
            "geometry_extent": "Bounding box of that geometry widened to a 0.001 degree grid (about "
            "110 m). The geometry itself is not kept.",
            "parameters": "Filters, distances, windows and other parameters of the operation.",
            "result_count": "Number of results returned (reads, exports) or features published (releases).",
        },
    )


def _functions(role: str) -> None:
    op.execute(
        """
        CREATE FUNCTION audit.coarse_extent(g public.geometry)
        RETURNS public.geometry
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        RETURN CASE
            WHEN g IS NULL OR public.ST_IsEmpty(g) THEN NULL
            ELSE public.ST_MakeEnvelope(
                floor(public.ST_XMin(g::public.box3d) * 1000) / 1000,
                floor(public.ST_YMin(g::public.box3d) * 1000) / 1000,
                (floor(public.ST_XMax(g::public.box3d) * 1000) + 1) / 1000,
                (floor(public.ST_YMax(g::public.box3d) * 1000) + 1) / 1000,
                4326)
        END
        """
    )
    op.execute(
        "COMMENT ON FUNCTION audit.coarse_extent(public.geometry) IS "
        "'Bounding box of a WGS84 geometry widened outwards to a 0.001 degree grid (about 110 m): the "
        "location detail the audit log keeps.'"
    )
    op.execute("REVOKE ALL ON FUNCTION audit.coarse_extent(public.geometry) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION audit.coarse_extent(public.geometry) TO {role}")

    op.execute(
        """
        CREATE FUNCTION audit.stamp_entry()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            -- Whatever the INSERT supplied: the transaction's context decides who, when and for whom.
            NEW.occurred_at := clock_timestamp();
            -- The transaction's tenant. Only a change recorded by the trigger below, in a transaction
            -- without a tenant (the owner editing rows by hand), keeps the tenant of the changed row.
            NEW.tenant_id := coalesce(
                meta.current_tenant_id(), CASE WHEN NEW.category = 'change' THEN NEW.tenant_id END);
            NEW.actor_subject := coalesce(
                nullif(current_setting('gis.actor_subject', true), ''), session_user);
            NEW.actor_client := nullif(current_setting('gis.actor_client', true), '');
            NEW.actor_roles := coalesce(
                string_to_array(nullif(current_setting('gis.actor_roles', true), ''), ','), '{}'::text[]);
            NEW.request_id := nullif(current_setting('gis.request_id', true), '');
            NEW.channel := coalesce(nullif(current_setting('gis.channel', true), ''), 'database');
            NEW.cross_tenant := coalesce(current_setting('gis.cross_tenant', true) = 'on', false)
                AND NEW.tenant_id IS NOT NULL;
            NEW.db_user := session_user;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION audit.refuse_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit entries are append-only (% refused)', TG_OP
                USING ERRCODE = '42501',
                      HINT = 'retention is an administrative act: disable the triggers explicitly';
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION audit.record_operational_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            subject constant text := TG_ARGV[0];
            retired_status constant text := TG_ARGV[1];
            retiring constant text := TG_ARGV[2];
            operation text;
            object_id uuid;
            owner text;
            shape public.geometry;
            details jsonb;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                operation := 'create';
                object_id := NEW.id;
                owner := NEW.tenant_id;
                shape := NEW.geom;
                details := jsonb_build_object(
                    'version', NEW.version, 'status', NEW.status,
                    'sharingPolicy', NEW.sharing_policy,
                    'sharedWithTenants', to_jsonb(NEW.shared_with_tenants));
            ELSIF TG_OP = 'DELETE' THEN
                operation := 'purge';
                object_id := OLD.id;
                owner := OLD.tenant_id;
                shape := OLD.geom;
                details := jsonb_build_object(
                    'version', OLD.version, 'status', OLD.status, 'sharingPolicy', OLD.sharing_policy);
            ELSE
                operation := CASE
                    WHEN NEW.status = retired_status AND OLD.status IS DISTINCT FROM NEW.status THEN retiring
                    ELSE 'update'
                END;
                object_id := NEW.id;
                owner := NEW.tenant_id;
                shape := NEW.geom;
                details := jsonb_build_object(
                    'version', NEW.version, 'previousVersion', OLD.version,
                    'status', NEW.status, 'previousStatus', OLD.status,
                    'sharingPolicy', NEW.sharing_policy, 'previousSharingPolicy', OLD.sharing_policy,
                    'sharedWithTenants', to_jsonb(NEW.shared_with_tenants),
                    'geometryChanged',
                        public.ST_AsEWKB(NEW.geom) IS DISTINCT FROM public.ST_AsEWKB(OLD.geom));
            END IF;
            IF subject = 'geofence' THEN
                IF TG_OP = 'DELETE' THEN
                    details := details || jsonb_build_object(
                        'kind', OLD.geofence_kind, 'radiusM', OLD.radius_m, 'areaM2', round(OLD.area_m2));
                ELSE
                    details := details || jsonb_build_object(
                        'kind', NEW.geofence_kind, 'radiusM', NEW.radius_m, 'areaM2', round(NEW.area_m2));
                END IF;
            END IF;
            INSERT INTO audit.entry
                (category, tenant_id, operation, target, object_id,
                 geometry_type, geometry_extent, parameters)
            VALUES (
                'change', owner, subject || '.' || operation, TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
                object_id::text, public.GeometryType(shape), audit.coarse_extent(shape),
                jsonb_strip_nulls(details));
            RETURN NULL;
        END
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION audit.record_release_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            release meta.ref_data_release;
            previous_status text;
            operations text[] := '{}';
            operation text;
            dataset_count bigint;
            feature_count bigint;
            rejected_count bigint;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                release := NEW;
                operations := ARRAY['create'];
            ELSIF TG_OP = 'DELETE' THEN
                release := OLD;
                operations := ARRAY['delete'];
            ELSE
                release := NEW;
                previous_status := OLD.status;
                IF NEW.status IS DISTINCT FROM OLD.status THEN
                    operations := operations || CASE NEW.status
                        WHEN 'published' THEN 'publish' WHEN 'retired' THEN 'retire' ELSE 'reopen' END;
                END IF;
                IF NEW.is_current AND NOT OLD.is_current THEN
                    operations := operations || 'make_current'::text;
                ELSIF OLD.is_current AND NOT NEW.is_current THEN
                    operations := operations || 'unset_current'::text;
                END IF;
            END IF;
            IF cardinality(operations) = 0 THEN
                RETURN NULL;  -- a description or timestamp changed: not a lifecycle event
            END IF;
            SELECT count(*), coalesce(sum(d.loaded_count), 0), coalesce(sum(d.rejected_count), 0)
            INTO dataset_count, feature_count, rejected_count
            FROM meta.dataset_load AS d
            WHERE d.release_id = release.id AND d.status = 'completed';
            FOREACH operation IN ARRAY operations LOOP
                INSERT INTO audit.entry (category, operation, target, object_id, parameters, result_count)
                VALUES (
                    'release', 'reference_release.' || operation, 'meta.ref_data_release', release.id::text,
                    jsonb_strip_nulls(jsonb_build_object(
                        'code', release.code,
                        'status', release.status,
                        'previousStatus', previous_status,
                        'isCurrent', release.is_current,
                        'datasets', dataset_count,
                        'rejectedFeatures', rejected_count)),
                    CASE WHEN operation IN ('publish', 'make_current') THEN feature_count END);
            END LOOP;
            RETURN NULL;
        END
        $$
        """
    )
    for name in (
        "stamp_entry()",
        "refuse_change()",
        "record_operational_change()",
        "record_release_change()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION audit.{name} FROM PUBLIC")


def _triggers_and_policies(role: str) -> None:
    op.execute(
        "CREATE TRIGGER a10_stamp_entry BEFORE INSERT ON audit.entry "
        "FOR EACH ROW EXECUTE FUNCTION audit.stamp_entry()"
    )
    op.execute(
        "CREATE TRIGGER a20_refuse_change BEFORE UPDATE OR DELETE ON audit.entry "
        "FOR EACH ROW EXECUTE FUNCTION audit.refuse_change()"
    )
    op.execute(
        "CREATE TRIGGER a20_refuse_truncate BEFORE TRUNCATE ON audit.entry "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit.refuse_change()"
    )
    # Default privileges already give the runtime login SELECT and INSERT only; say so explicitly.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit.entry FROM {role}")
    op.execute("ALTER TABLE audit.entry ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY entry_select ON audit.entry FOR SELECT USING ("
        "tenant_id = meta.current_tenant_id() "
        "OR (tenant_id IS NULL AND meta.current_tenant_id() IS NULL))"
    )
    op.execute(
        "CREATE POLICY entry_insert ON audit.entry FOR INSERT "
        "WITH CHECK (tenant_id IS NOT DISTINCT FROM meta.current_tenant_id())"
    )
    for table, subject, retired, retiring in AUDITED_OPERATIONAL_TABLES:
        op.execute(
            f"CREATE TRIGGER z90_audit_change AFTER INSERT OR UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION audit.record_operational_change('{subject}', '{retired}', "
            f"'{retiring}')"
        )
    op.execute(
        "CREATE TRIGGER z90_audit_change AFTER INSERT OR UPDATE OR DELETE ON meta.ref_data_release "
        "FOR EACH ROW EXECUTE FUNCTION audit.record_release_change()"
    )


def upgrade() -> None:
    role = app_role()
    _table()
    _functions(role)
    _triggers_and_policies(role)


def downgrade() -> None:
    # The audit log is evidence: refuse rather than discard it.
    refuse_if_not_empty(["audit.entry"])
    op.execute("DROP TRIGGER z90_audit_change ON meta.ref_data_release")
    for table, _, _, _ in reversed(AUDITED_OPERATIONAL_TABLES):
        op.execute(f"DROP TRIGGER z90_audit_change ON {table}")
    op.execute("DROP TABLE audit.entry")
    for name in (
        "record_release_change()",
        "record_operational_change()",
        "refuse_change()",
        "stamp_entry()",
        "coarse_extent(public.geometry)",
    ):
        op.execute(f"DROP FUNCTION audit.{name}")
