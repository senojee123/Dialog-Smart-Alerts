"""Metadata registry, reference data releases, lineage and shared spatial functions.

Creates the ``meta`` objects every spatial table depends on:

* ``meta.tenant``            organisations and authorities that own operational data and events
* ``meta.data_source``       publishers and licences of reference data (licence guard for commercial use)
* ``meta.ref_data_release``  versioned, immutable-once-published reference data releases
* ``meta.layer``             registry of spatial layers (filled by the migrations that create the tables)
* ``meta.dataset_load``      lineage: one row per source file loaded into a release
* ``meta.geometry_repair``   log of reference geometries repaired on load

and the database functions the constraints and triggers of later revisions use:

* ``meta.is_within_sri_lanka(geometry)`` / ``meta.sri_lanka_bounds()``  service-area envelope check
* ``meta.repair_polygonal(geometry)``  make polygon(s) valid, keep only the polygonal part
* ``meta.sector_polygon(...)``  camera field-of-view sector, computed in EPSG:5235
* ``meta.current_tenant_is_authority()``  row-level security helper
* trigger functions for ``updated_at``, row versions, release guards and reference geometry repair

Requires PostgreSQL 18 (``uuidv7()``) and ``btree_gist`` (GiST indexes and exclusion constraints that
combine scalar columns with geometries or time ranges).

Revision ID: 20260915_0002
Revises: 20260915_0001
Create Date: 2026-09-15 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from migration_support import app_role, comment_columns, comment_table, refuse_if_not_empty, touch_trigger

revision: str = "20260915_0002"
down_revision: str | Sequence[str] | None = "20260915_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Service-area envelope (WGS84). Keep in step with DEFAULT_SERVICE_AREA_BBOX in app/core/config.py;
# tests/integration/test_spatial_model.py asserts that they match.
MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = 79.44, 5.66, 82.15, 10.08

TENANT_ID_PATTERN = "^[a-z0-9][a-z0-9_-]{1,62}$"
RELEASE_CODE_PATTERN = r"^ref-[0-9]{4}\.[0-9]{2}(-[a-z0-9]+)*$"


def _functions() -> None:
    op.execute(
        f"""
        CREATE FUNCTION meta.sri_lanka_bounds()
        RETURNS public.box2d
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        RETURN public.ST_MakeBox2D(
            public.ST_Point({MIN_LON}, {MIN_LAT}, 4326), public.ST_Point({MAX_LON}, {MAX_LAT}, 4326)
        )
        """
    )
    # Box3D keeps double precision; box2d rounds to float4 and would misjudge points on the envelope.
    op.execute(
        f"""
        CREATE FUNCTION meta.is_within_sri_lanka(g public.geometry)
        RETURNS boolean
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        RETURN public.ST_SRID(g) = 4326
            AND public.ST_XMin(public.Box3D(g)) >= {MIN_LON}
            AND public.ST_YMin(public.Box3D(g)) >= {MIN_LAT}
            AND public.ST_XMax(public.Box3D(g)) <= {MAX_LON}
            AND public.ST_YMax(public.Box3D(g)) <= {MAX_LAT}
        """
    )
    op.execute(
        """
        CREATE FUNCTION meta.repair_polygonal(g public.geometry)
        RETURNS public.geometry
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        RETURN CASE
            WHEN public.ST_IsValid(g, 0) THEN public.ST_Multi(g)
            ELSE public.ST_Multi(
                public.ST_CollectionExtract(public.ST_MakeValid(g, 'method=structure keepcollapsed=false'), 3)
            )
        END
        """
    )
    op.execute(
        """
        CREATE FUNCTION meta.sector_polygon(
            center public.geometry,
            bearing_deg double precision,
            fov_deg double precision,
            range_m double precision,
            segments integer DEFAULT 32
        )
        RETURNS public.geometry
        LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            origin public.geometry;
            start_deg double precision;
            ring public.geometry[];
        BEGIN
            IF public.GeometryType(center) <> 'POINT' OR public.ST_SRID(center) <> 4326 THEN
                RAISE EXCEPTION 'sector centre must be an EPSG:4326 point' USING ERRCODE = '22023';
            END IF;
            IF bearing_deg < 0 OR bearing_deg >= 360 THEN
                RAISE EXCEPTION 'bearing must be in [0, 360) degrees, got %', bearing_deg
                    USING ERRCODE = '22023';
            END IF;
            IF fov_deg <= 0 OR fov_deg > 360 THEN
                RAISE EXCEPTION 'field of view must be in (0, 360] degrees, got %', fov_deg
                    USING ERRCODE = '22023';
            END IF;
            IF range_m <= 0 THEN
                RAISE EXCEPTION 'range must be positive, got %', range_m USING ERRCODE = '22023';
            END IF;
            IF segments < 4 OR segments > 720 THEN
                RAISE EXCEPTION 'segments must be between 4 and 720, got %', segments USING ERRCODE = '22023';
            END IF;

            origin := public.ST_Transform(center, 5235);
            IF fov_deg = 360 THEN
                RETURN public.ST_Multi(public.ST_Transform(
                    public.ST_Buffer(origin, range_m, 'quad_segs=' || greatest(segments / 4, 2)), 4326));
            END IF;

            -- Bearings are clockwise from SLD99 grid north (within 0.2 degrees of true north on the island).
            -- The arc is built in metres; the apex is the device position itself, so that the sector
            -- starts exactly at the device (a round trip through EPSG:5235 would move it by millimetres).
            start_deg := bearing_deg - fov_deg / 2;
            ring := ARRAY[center]
                || ARRAY(
                    SELECT public.ST_Transform(
                        public.ST_Translate(
                            origin,
                            range_m * sind(start_deg + i * fov_deg / segments),
                            range_m * cosd(start_deg + i * fov_deg / segments)),
                        4326)
                    FROM generate_series(0, segments) AS i
                    ORDER BY i)
                || ARRAY[center];
            RETURN public.ST_Multi(public.ST_MakePolygon(public.ST_MakeLine(ring)));
        END
        $$
        """
    )

    # Trigger functions.
    op.execute(
        """
        CREATE FUNCTION meta.touch_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION meta.bump_row_version()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            NEW.version := OLD.version + 1;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION meta.guard_release_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'published' THEN
                    RAISE EXCEPTION 'reference data release % is published; retire it before deleting it',
                        OLD.code
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'draft' THEN
                    RAISE EXCEPTION 'a new reference data release must start as draft'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            IF NEW.code <> OLD.code THEN
                RAISE EXCEPTION 'the code of reference data release % cannot change', OLD.code
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status <> OLD.status THEN
                IF NOT (OLD.status, NEW.status) IN (('draft', 'published'), ('published', 'retired')) THEN
                    RAISE EXCEPTION 'reference data release % cannot move from % to %',
                        OLD.code, OLD.status, NEW.status
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.status = 'published' THEN
                    IF EXISTS (
                        SELECT 1 FROM meta.dataset_load AS l
                        WHERE l.release_id = NEW.id AND l.status = 'running'
                    ) THEN
                        RAISE EXCEPTION 'reference data release % has loads still running', NEW.code
                            USING ERRCODE = '55000';
                    END IF;
                    NEW.published_at := now();
                ELSE
                    NEW.retired_at := now();
                    NEW.is_current := false;
                END IF;
            ELSIF NEW.published_at IS DISTINCT FROM OLD.published_at
                OR NEW.retired_at IS DISTINCT FROM OLD.retired_at THEN
                RAISE EXCEPTION 'publication timestamps of release % are maintained by the database', OLD.code
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    # Reference rows and loads may change only while their release is a draft. Rows of a retired
    # release may be deleted (purge); a missing release means it is being deleted in this statement,
    # which guard_release_transition has already allowed.
    op.execute(
        """
        CREATE FUNCTION meta.guard_release_is_draft()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            release_status text;
            release_code text;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                SELECT r.status, r.code INTO release_status, release_code
                FROM meta.ref_data_release AS r WHERE r.id = OLD.release_id;
                IF release_status = 'published' OR (TG_OP = 'UPDATE' AND release_status = 'retired') THEN
                    RAISE EXCEPTION '% of %.% rejected: reference data release % is %',
                        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME, release_code, release_status
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                SELECT r.status, r.code INTO release_status, release_code
                FROM meta.ref_data_release AS r WHERE r.id = NEW.release_id;
                IF release_status IS DISTINCT FROM 'draft' AND release_status IS NOT NULL THEN
                    RAISE EXCEPTION '% of %.% rejected: reference data release % is %',
                        TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME, release_code, release_status
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            RETURN OLD;
        END
        $$
        """
    )
    # Reference geometries: lines and polygons are stored as multi-geometries (PostGIS already promotes
    # them for multi-typed columns; this covers the mixed-type columns of settlement and water_body).
    # Invalid polygons are repaired (ST_MakeValid, structure method) and the original is logged; a
    # polygon that collapses to nothing is rejected.
    op.execute(
        """
        CREATE FUNCTION meta.normalise_reference_geometry()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            kind text := public.GeometryType(NEW.geom);
            repaired public.geometry;
            reason text;
        BEGIN
            IF kind IN ('LINESTRING', 'POLYGON') THEN
                NEW.geom := public.ST_Multi(NEW.geom);
            END IF;
            IF kind IN ('POLYGON', 'MULTIPOLYGON') AND NOT public.ST_IsValid(NEW.geom, 0) THEN
                reason := public.ST_IsValidReason(NEW.geom);
                repaired := meta.repair_polygonal(NEW.geom);
                IF repaired IS NULL OR public.ST_IsEmpty(repaired) THEN
                    RAISE EXCEPTION 'invalid polygon in %.% cannot be repaired: %',
                        TG_TABLE_SCHEMA, TG_TABLE_NAME, reason
                        USING ERRCODE = '22023';
                END IF;
                INSERT INTO meta.geometry_repair (
                    table_schema, table_name, feature_id, load_id, reason, original_geom,
                    original_area_m2, repaired_area_m2)
                VALUES (
                    TG_TABLE_SCHEMA, TG_TABLE_NAME, NEW.id, NEW.load_id, reason, NEW.geom,
                    public.ST_Area(public.ST_Transform(NEW.geom, 5235)),
                    public.ST_Area(public.ST_Transform(repaired, 5235)));
                NEW.geom := repaired;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        COMMENT ON FUNCTION meta.is_within_sri_lanka(public.geometry) IS
        'True when the geometry is EPSG:4326 and its exact envelope lies inside the service area '
        '(lon 79.44..82.15, lat 5.66..10.08). Used by CHECK constraints on every spatial table.'
        """
    )
    op.execute(
        """
        COMMENT ON FUNCTION meta.sector_polygon(public.geometry, double precision, double precision,
            double precision, integer) IS
        'Field-of-view sector as an EPSG:4326 MultiPolygon. Built in EPSG:5235 from the device position, '
        'bearing (degrees clockwise from north), field of view and range in metres; 360 degrees gives a disc.'
        """
    )
    op.execute(
        """
        COMMENT ON FUNCTION meta.repair_polygonal(public.geometry) IS
        'Valid polygonal part of a geometry as a MultiPolygon (ST_MakeValid structure method). '
        'Returns an empty geometry when nothing polygonal remains.'
        """
    )


def _tables() -> None:
    op.execute(
        f"""
        CREATE TABLE meta.tenant (
            tenant_id text NOT NULL,
            name text NOT NULL,
            kind text NOT NULL DEFAULT 'organisation',
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_tenant PRIMARY KEY (tenant_id),
            CONSTRAINT ck_tenant_tenant_id_format CHECK (tenant_id ~ '{TENANT_ID_PATTERN}'),
            CONSTRAINT ck_tenant_kind CHECK (kind IN ('organisation', 'authority')),
            CONSTRAINT ck_tenant_name_not_blank CHECK (btrim(name) <> '')
        )
        """
    )
    comment_table(
        "meta.tenant",
        "Organisations and authorities that own operational geodata and events. Provisioned by an "
        "administrator; read-only for the API.",
    )
    comment_columns(
        "meta.tenant",
        {
            "tenant_id": "Stable identifier used in gis.tenant_id and every tenant_id column.",
            "kind": "organisation, or authority (may read rows shared with authorities).",
        },
    )
    touch_trigger("meta.tenant")

    op.execute(
        """
        CREATE TABLE meta.data_source (
            id uuid NOT NULL DEFAULT uuidv7(),
            code text NOT NULL,
            name text NOT NULL,
            publisher text NOT NULL,
            url text,
            licence text NOT NULL,
            licence_url text,
            attribution text NOT NULL,
            commercial_use_allowed boolean NOT NULL,
            share_alike boolean NOT NULL DEFAULT false,
            permission_reference text,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_data_source PRIMARY KEY (id),
            CONSTRAINT uq_data_source_code UNIQUE (code),
            CONSTRAINT ck_data_source_code_format CHECK (code ~ '^[a-z0-9][a-z0-9_.-]{1,62}$'),
            CONSTRAINT ck_data_source_commercial_use_permitted
                CHECK (commercial_use_allowed OR permission_reference IS NOT NULL)
        )
        """
    )
    comment_table(
        "meta.data_source",
        "Publisher and licence of a reference dataset. A source whose licence does not allow commercial "
        "use can only be registered with the reference of a written permission.",
    )
    comment_columns(
        "meta.data_source",
        {
            "licence": "Licence identifier, SPDX where one exists (ODbL-1.0, CC-BY-3.0-IGO, ...).",
            "attribution": "Attribution text that must accompany maps and exports using this source.",
            "commercial_use_allowed": "Whether the licence itself permits use in a commercial service.",
            "permission_reference": "Agreement or letter granting use when the licence does not.",
        },
    )
    touch_trigger("meta.data_source")

    op.execute(
        f"""
        CREATE TABLE meta.ref_data_release (
            id uuid NOT NULL DEFAULT uuidv7(),
            code text NOT NULL,
            description text,
            status text NOT NULL DEFAULT 'draft',
            is_current boolean NOT NULL DEFAULT false,
            published_at timestamptz,
            retired_at timestamptz,
            created_by text NOT NULL DEFAULT CURRENT_USER,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_ref_data_release PRIMARY KEY (id),
            CONSTRAINT uq_ref_data_release_code UNIQUE (code),
            CONSTRAINT ck_ref_data_release_code_format CHECK (code ~ '{RELEASE_CODE_PATTERN}'),
            CONSTRAINT ck_ref_data_release_status CHECK (status IN ('draft', 'published', 'retired')),
            CONSTRAINT ck_ref_data_release_current_is_published
                CHECK (NOT is_current OR status = 'published'),
            CONSTRAINT ck_ref_data_release_published_at CHECK ((status = 'draft') = (published_at IS NULL)),
            CONSTRAINT ck_ref_data_release_retired_at CHECK ((status = 'retired') = (retired_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_ref_data_release_is_current ON meta.ref_data_release (is_current) "
        "WHERE is_current"
    )
    comment_table(
        "meta.ref_data_release",
        "Versioned reference data release (ref-YYYY.MM). Rows are loaded into a draft; a published "
        "release is immutable. Exactly one published release is current.",
    )
    comment_columns(
        "meta.ref_data_release",
        {
            "status": "draft -> published -> retired (enforced by trigger).",
            "is_current": "The release geo-context uses by default. At most one row is current.",
        },
    )
    op.execute(
        "CREATE TRIGGER a10_guard_release_transition BEFORE INSERT OR UPDATE OR DELETE "
        "ON meta.ref_data_release FOR EACH ROW EXECUTE FUNCTION meta.guard_release_transition()"
    )
    touch_trigger("meta.ref_data_release")

    op.execute(
        """
        CREATE TABLE meta.layer (
            id uuid NOT NULL DEFAULT uuidv7(),
            code text NOT NULL,
            name text NOT NULL,
            description text NOT NULL,
            layer_group text NOT NULL,
            table_schema text NOT NULL,
            table_name text NOT NULL,
            geometry_column text NOT NULL DEFAULT 'geom',
            geometry_types text[] NOT NULL,
            srid integer NOT NULL DEFAULT 4326,
            metric_srid integer NOT NULL DEFAULT 5235,
            tenant_scoped boolean NOT NULL,
            default_sharing_policy text,
            update_frequency text NOT NULL,
            nominal_accuracy_m numeric(10, 2),
            is_published boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_layer PRIMARY KEY (id),
            CONSTRAINT uq_layer_code UNIQUE (code),
            CONSTRAINT uq_layer_table_schema_table_name_geometry_column
                UNIQUE (table_schema, table_name, geometry_column),
            CONSTRAINT ck_layer_code_is_table CHECK (code = table_schema || '.' || table_name),
            CONSTRAINT ck_layer_layer_group CHECK (layer_group IN ('reference', 'operational', 'event')),
            CONSTRAINT ck_layer_geometry_types CHECK (
                cardinality(geometry_types) > 0
                AND geometry_types <@ ARRAY['POINT', 'LINESTRING', 'POLYGON', 'MULTIPOINT',
                                            'MULTILINESTRING', 'MULTIPOLYGON']::text[]
            ),
            CONSTRAINT ck_layer_srid CHECK (srid = 4326),
            CONSTRAINT ck_layer_metric_srid CHECK (metric_srid = 5235),
            CONSTRAINT ck_layer_sharing_policy CHECK (
                default_sharing_policy IS NULL
                OR (tenant_scoped AND default_sharing_policy IN ('private', 'shared', 'authority_only'))
            ),
            CONSTRAINT ck_layer_update_frequency
                CHECK (update_frequency IN ('release', 'on_change', 'continuous')),
            CONSTRAINT ck_layer_nominal_accuracy_m CHECK (nominal_accuracy_m > 0)
        )
        """
    )
    comment_table(
        "meta.layer",
        "Registry of spatial layers: table, geometry types, CRS, tenancy and update pattern. Rows are "
        "maintained by the migration that creates the layer table.",
    )
    comment_columns(
        "meta.layer",
        {
            "code": "Layer code; equal to the schema-qualified table name.",
            "srid": "Canonical storage CRS (always EPSG:4326).",
            "metric_srid": "CRS of the metric twin column geom_metric (always EPSG:5235, SLD99).",
            "update_frequency": "release: changes only through reference data releases; on_change: "
            "edited by tenants; continuous: event stream.",
            "nominal_accuracy_m": "Typical positional accuracy of the layer in metres (informative).",
        },
    )
    touch_trigger("meta.layer")

    op.execute(
        """
        CREATE TABLE meta.dataset_load (
            id uuid NOT NULL DEFAULT uuidv7(),
            release_id uuid NOT NULL,
            layer_id uuid NOT NULL,
            source_id uuid NOT NULL,
            source_version text,
            source_file text NOT NULL,
            source_checksum_sha256 text NOT NULL,
            source_crs text NOT NULL,
            source_feature_count integer NOT NULL DEFAULT 0,
            transformation text NOT NULL,
            loader_version text NOT NULL,
            status text NOT NULL DEFAULT 'running',
            loaded_count integer NOT NULL DEFAULT 0,
            repaired_count integer NOT NULL DEFAULT 0,
            rejected_count integer NOT NULL DEFAULT 0,
            message text,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz,
            loaded_by text NOT NULL DEFAULT CURRENT_USER,
            CONSTRAINT pk_dataset_load PRIMARY KEY (id),
            CONSTRAINT uq_dataset_load_id_release_id UNIQUE (id, release_id),
            CONSTRAINT fk_dataset_load_release_id_ref_data_release FOREIGN KEY (release_id)
                REFERENCES meta.ref_data_release (id) ON DELETE CASCADE,
            CONSTRAINT fk_dataset_load_layer_id_layer FOREIGN KEY (layer_id)
                REFERENCES meta.layer (id) ON DELETE RESTRICT,
            CONSTRAINT fk_dataset_load_source_id_data_source FOREIGN KEY (source_id)
                REFERENCES meta.data_source (id) ON DELETE RESTRICT,
            CONSTRAINT ck_dataset_load_checksum_format CHECK (source_checksum_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_dataset_load_status CHECK (status IN ('running', 'completed', 'failed')),
            CONSTRAINT ck_dataset_load_counts CHECK (
                source_feature_count >= 0 AND loaded_count >= 0
                AND repaired_count >= 0 AND rejected_count >= 0
                AND repaired_count <= loaded_count
            ),
            CONSTRAINT ck_dataset_load_finished_at CHECK (
                (status = 'running') = (finished_at IS NULL)
                AND (finished_at IS NULL OR finished_at >= started_at)
            )
        )
        """
    )
    op.execute("CREATE INDEX ix_dataset_load_release_id_layer_id ON meta.dataset_load (release_id, layer_id)")
    op.execute("CREATE INDEX ix_dataset_load_layer_id ON meta.dataset_load (layer_id)")
    op.execute("CREATE INDEX ix_dataset_load_source_id ON meta.dataset_load (source_id)")
    op.execute("CREATE INDEX ix_dataset_load_started_at ON meta.dataset_load (started_at)")
    op.execute(
        "CREATE UNIQUE INDEX uq_dataset_load_file_once_per_release ON meta.dataset_load "
        "(release_id, layer_id, source_checksum_sha256) WHERE status <> 'failed'"
    )
    op.execute(
        "CREATE TRIGGER a10_guard_release_is_draft BEFORE INSERT OR UPDATE OR DELETE ON meta.dataset_load "
        "FOR EACH ROW EXECUTE FUNCTION meta.guard_release_is_draft()"
    )
    comment_table(
        "meta.dataset_load",
        "Lineage of reference data: one row per source file loaded into a release, with checksum, source "
        "CRS, transformation and counts. Deleting a load deletes the features it loaded.",
    )
    comment_columns(
        "meta.dataset_load",
        {
            "source_crs": "CRS of the source file, e.g. EPSG:4326 or EPSG:5235.",
            "transformation": "Coordinate operation and processing applied (for example the PROJ pipeline).",
            "loader_version": "Version of the loader that produced the rows.",
            "repaired_count": "Features whose polygons were repaired (see meta.geometry_repair).",
            "rejected_count": "Source features not loaded (outside the service area, empty, ...).",
        },
    )

    op.execute(
        """
        CREATE TABLE meta.geometry_repair (
            id bigint GENERATED ALWAYS AS IDENTITY,
            table_schema text NOT NULL,
            table_name text NOT NULL,
            feature_id uuid NOT NULL,
            load_id uuid NOT NULL,
            reason text NOT NULL,
            original_geom public.geometry(Geometry, 4326) NOT NULL,
            original_area_m2 double precision,
            repaired_area_m2 double precision,
            repaired_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_geometry_repair PRIMARY KEY (id),
            CONSTRAINT fk_geometry_repair_load_id_dataset_load FOREIGN KEY (load_id)
                REFERENCES meta.dataset_load (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX ix_geometry_repair_load_id ON meta.geometry_repair (load_id)")
    op.execute(
        "CREATE INDEX ix_geometry_repair_table_schema_table_name_feature_id "
        "ON meta.geometry_repair (table_schema, table_name, feature_id)"
    )
    comment_table(
        "meta.geometry_repair",
        "Reference geometries repaired on load: the reason reported by ST_IsValidReason, the original "
        "geometry and the area before and after repair (EPSG:5235).",
    )


def _tenant_functions() -> None:
    """Row-level security helper; its SQL-standard body is bound to meta.tenant, so it follows the table."""
    op.execute(
        """
        CREATE FUNCTION meta.current_tenant_is_authority()
        RETURNS boolean
        LANGUAGE sql STABLE PARALLEL SAFE
        RETURN coalesce(
            (SELECT t.kind = 'authority' AND t.is_active
             FROM meta.tenant AS t
             WHERE t.tenant_id = meta.current_tenant_id()),
            false)
        """
    )
    op.execute(
        "COMMENT ON FUNCTION meta.current_tenant_is_authority() IS "
        "'True when the tenant of the current transaction is an active authority.'"
    )
    role = app_role()
    op.execute("REVOKE ALL ON FUNCTION meta.current_tenant_is_authority() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION meta.current_tenant_is_authority() TO {role}")


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF current_setting('server_version_num')::integer < 180000 THEN
                RAISE EXCEPTION 'PostgreSQL 18 or later is required (uuidv7)';
            END IF;
        END
        $$
        """
    )
    # Trusted extension: the database owner (the migration login) may create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public")
    _functions()
    _tables()
    _tenant_functions()


def downgrade() -> None:
    refuse_if_not_empty(
        [
            "meta.geometry_repair",
            "meta.dataset_load",
            "meta.layer",
            "meta.ref_data_release",
            "meta.data_source",
            "meta.tenant",
        ]
    )
    for table in ("geometry_repair", "dataset_load", "layer", "ref_data_release", "data_source"):
        op.execute(f"DROP TABLE meta.{table}")
    op.execute("DROP FUNCTION meta.current_tenant_is_authority()")
    op.execute("DROP TABLE meta.tenant")
    for signature in (
        "normalise_reference_geometry()",
        "guard_release_is_draft()",
        "guard_release_transition()",
        "bump_row_version()",
        "touch_updated_at()",
        "sector_polygon(public.geometry, double precision, double precision, double precision, integer)",
        "repair_polygonal(public.geometry)",
        "is_within_sri_lanka(public.geometry)",
        "sri_lanka_bounds()",
    ):
        op.execute(f"DROP FUNCTION meta.{signature}")
    # btree_gist stays installed, like PostGIS: extensions are shared database infrastructure.
