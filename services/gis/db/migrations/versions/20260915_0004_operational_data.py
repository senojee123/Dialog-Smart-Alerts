"""Operational layers (schema ``ops``): sites, devices, device fields of view and geofences.

Tenant-owned data, protected by row-level security:

* read: the owning tenant; tenants listed in ``shared_with_tenants`` when ``sharing_policy = 'shared'``;
  authority tenants when ``sharing_policy`` is ``shared`` or ``authority_only``
* insert, update, delete: the owning tenant only

``ops.device_field_of_view`` follows the visibility of its device. Tenant consistency between related
rows (site -> device -> field of view) is enforced with composite foreign keys on ``(id, tenant_id)``.

Geometry rules:

* sites and devices are EPSG:4326 points with a stored EPSG:5235 twin
* a modelled field of view is computed by the database from the device position, bearing, angle and
  range (``meta.sector_polygon``); an open period follows the device when it moves, a closed period keeps
  its sector. A surveyed field of view is supplied as a polygon or multipolygon
* geofences are defined as a polygon, a circle (point + radius) or a corridor (line + half-width).
  The database derives the search polygon in EPSG:5235 and its EPSG:4326 copy. Invalid definitions are
  rejected (SQLSTATE 22023), never repaired silently.

Revision ID: 20260915_0004
Revises: 20260915_0003
Create Date: 2026-09-15 00:00:03+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from migration_support import (
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
    version_trigger,
)

revision: str = "20260915_0004"
down_revision: str | Sequence[str] | None = "20260915_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SHARED_READ = (
    "tenant_id = meta.current_tenant_id()"
    " OR (sharing_policy = 'shared' AND shared_with_tenants @> ARRAY[meta.current_tenant_id()])"
    " OR (sharing_policy IN ('shared', 'authority_only') AND (SELECT meta.current_tenant_is_authority()))"
)
# A field of view is visible exactly when its device is (the subquery is itself subject to RLS).
DEVICE_READ = "EXISTS (SELECT 1 FROM ops.device AS d WHERE d.id = device_id)"

POSITION_SOURCES = "('survey', 'gps', 'digitised', 'imagery', 'estimated')"

# Circle and corridor search polygons circumscribe the exact buffer: vertices are placed at
# radius / cos(pi / (4 * QUAD_SEGS)), so every point within the radius lies inside the polygon and the
# spatial index never misses a hit. The exact test is ST_DWithin(definition_metric, point, radius_m).
QUAD_SEGS = 32


def _tenancy_columns(name: str) -> tuple[list[str], list[str]]:
    columns = [
        "tenant_id text NOT NULL DEFAULT meta.current_tenant_id()",
        "sharing_policy text NOT NULL DEFAULT 'private'",
        "shared_with_tenants text[] NOT NULL DEFAULT '{}'::text[]",
    ]
    constraints = [
        f"CONSTRAINT fk_{name}_tenant_id_tenant FOREIGN KEY (tenant_id) "
        "REFERENCES meta.tenant (tenant_id) ON DELETE RESTRICT",
        f"CONSTRAINT ck_{name}_sharing_policy "
        "CHECK (sharing_policy IN ('private', 'shared', 'authority_only'))",
        f"CONSTRAINT ck_{name}_shared_with_tenants CHECK ("
        "(sharing_policy = 'shared' OR cardinality(shared_with_tenants) = 0) "
        "AND array_position(shared_with_tenants, NULL) IS NULL "
        "AND NOT (tenant_id = ANY (shared_with_tenants)))",
    ]
    return columns, constraints


def _audit_columns(name: str) -> tuple[list[str], list[str]]:
    columns = [
        "attributes jsonb NOT NULL DEFAULT '{}'::jsonb",
        "version integer NOT NULL DEFAULT 1",
        "created_by text",
        "updated_by text",
        "created_at timestamptz NOT NULL DEFAULT now()",
        "updated_at timestamptz NOT NULL DEFAULT now()",
    ]
    constraints = [
        f"CONSTRAINT ck_{name}_attributes_is_object CHECK (jsonb_typeof(attributes) = 'object')",
        f"CONSTRAINT ck_{name}_version CHECK (version >= 1)",
    ]
    return columns, constraints


AUDIT_COMMENTS = {
    "version": "Row version, incremented on every update (optimistic concurrency).",
    "created_by": "Identity of the user or client that created the row, as supplied by the API.",
    "updated_by": "Identity of the user or client that last changed the row, as supplied by the API.",
}
TENANCY_COMMENTS = {
    **AUDIT_COMMENTS,
    "tenant_id": "Owning tenant. Defaults to the tenant of the current transaction.",
    "sharing_policy": "private (owner only), shared (owner, listed tenants and authorities) or "
    "authority_only (owner and authorities).",
    "shared_with_tenants": "Tenants that may read the row when sharing_policy = 'shared'.",
}


def _create(name: str, columns: list[str], constraints: list[str]) -> None:
    body = ",\n    ".join(columns + constraints)
    op.execute(f"CREATE TABLE ops.{name} (\n    {body}\n)")


def _site() -> None:
    tenancy, tenancy_constraints = _tenancy_columns("site")
    audit, audit_constraints = _audit_columns("site")
    _create(
        "site",
        [
            "id uuid NOT NULL DEFAULT uuidv7()",
            *tenancy,
            "external_id text",
            "name text NOT NULL",
            "site_type text NOT NULL DEFAULT 'other'",
            "status text NOT NULL DEFAULT 'active'",
            "geom public.geometry(Point, 4326) NOT NULL",
            metric_twin("geom", "Point"),
            "position_source text NOT NULL",
            "position_accuracy_m numeric(10, 2)",
            *audit,
        ],
        [
            "CONSTRAINT pk_site PRIMARY KEY (id)",
            "CONSTRAINT uq_site_id_tenant_id UNIQUE (id, tenant_id)",
            "CONSTRAINT uq_site_tenant_id_external_id UNIQUE (tenant_id, external_id)",
            *tenancy_constraints,
            "CONSTRAINT ck_site_site_type CHECK (site_type IN "
            "('pole', 'building', 'junction', 'checkpoint', 'estate', 'perimeter', 'other'))",
            "CONSTRAINT ck_site_status CHECK (status IN ('planned', 'active', 'decommissioned'))",
            f"CONSTRAINT ck_site_position_source CHECK (position_source IN {POSITION_SOURCES})",
            "CONSTRAINT ck_site_position_accuracy_m CHECK (position_accuracy_m > 0)",
            "CONSTRAINT ck_site_name_not_blank CHECK (btrim(name) <> '')",
            geometry_checks("ops.site"),
            *audit_constraints,
        ],
    )
    gist_index("ops.site", "geom")
    gist_index("ops.site", "geom_metric")
    version_trigger("ops.site")
    touch_trigger("ops.site")
    comment_table("ops.site", "Installation sites (poles, buildings, checkpoints) owned by a tenant.")
    comment_columns(
        "ops.site",
        {
            **TENANCY_COMMENTS,
            "external_id": "Identifier of the site in the tenant's own systems.",
            "geom": "Site position, EPSG:4326.",
            "geom_metric": "Stored EPSG:5235 copy of geom.",
            "position_source": "How the position was obtained.",
            "position_accuracy_m": "Estimated horizontal accuracy of the position in metres.",
        },
    )


def _device() -> None:
    tenancy, tenancy_constraints = _tenancy_columns("device")
    audit, audit_constraints = _audit_columns("device")
    _create(
        "device",
        [
            "id uuid NOT NULL DEFAULT uuidv7()",
            *tenancy,
            "site_id uuid",
            "external_id text",
            "name text NOT NULL",
            "device_type text NOT NULL",
            "status text NOT NULL DEFAULT 'active'",
            "mounting_height_m numeric(6, 2)",
            "geom public.geometry(Point, 4326) NOT NULL",
            metric_twin("geom", "Point"),
            "position_source text NOT NULL",
            "position_accuracy_m numeric(10, 2)",
            "installed_at timestamptz",
            "decommissioned_at timestamptz",
            *audit,
        ],
        [
            "CONSTRAINT pk_device PRIMARY KEY (id)",
            "CONSTRAINT uq_device_id_tenant_id UNIQUE (id, tenant_id)",
            "CONSTRAINT uq_device_tenant_id_external_id UNIQUE (tenant_id, external_id)",
            *tenancy_constraints,
            "CONSTRAINT fk_device_site_id_tenant_id_site FOREIGN KEY (site_id, tenant_id) "
            "REFERENCES ops.site (id, tenant_id) ON DELETE SET NULL (site_id)",
            "CONSTRAINT ck_device_device_type CHECK (device_type IN ('camera', 'anpr_camera', "
            "'acoustic_sensor', 'seismic_sensor', 'environmental_sensor', 'gateway', 'other'))",
            "CONSTRAINT ck_device_status "
            "CHECK (status IN ('planned', 'active', 'inactive', 'decommissioned'))",
            "CONSTRAINT ck_device_mounting_height_m "
            "CHECK (mounting_height_m >= 0 AND mounting_height_m <= 500)",
            f"CONSTRAINT ck_device_position_source CHECK (position_source IN {POSITION_SOURCES})",
            "CONSTRAINT ck_device_position_accuracy_m CHECK (position_accuracy_m > 0)",
            "CONSTRAINT ck_device_service_period CHECK (decommissioned_at IS NULL OR installed_at IS NULL "
            "OR decommissioned_at >= installed_at)",
            "CONSTRAINT ck_device_name_not_blank CHECK (btrim(name) <> '')",
            geometry_checks("ops.device"),
            *audit_constraints,
        ],
    )
    gist_index("ops.device", "geom")
    gist_index("ops.device", "geom_metric")
    op.execute("CREATE INDEX ix_device_site_id ON ops.device (site_id)")
    version_trigger("ops.device")
    touch_trigger("ops.device")
    comment_table("ops.device", "Cameras and sensors owned by a tenant, optionally installed at a site.")
    comment_columns(
        "ops.device",
        {
            **TENANCY_COMMENTS,
            "site_id": "Site the device is installed at (same tenant).",
            "external_id": "Identifier of the device in the tenant's own systems.",
            "mounting_height_m": "Height of the device above ground in metres.",
            "geom": "Installed position, EPSG:4326.",
            "geom_metric": "Stored EPSG:5235 copy of geom; used for nearest-device searches.",
            "position_source": "How the position was obtained.",
            "position_accuracy_m": "Estimated horizontal accuracy of the position in metres.",
        },
    )


def _field_of_view() -> None:
    audit, audit_constraints = _audit_columns("device_field_of_view")
    _create(
        "device_field_of_view",
        [
            "id uuid NOT NULL DEFAULT uuidv7()",
            "tenant_id text NOT NULL DEFAULT meta.current_tenant_id()",
            "device_id uuid NOT NULL",
            "geometry_method text NOT NULL",
            "bearing_deg numeric(5, 2)",
            "fov_deg numeric(5, 2)",
            "range_m numeric(8, 2)",
            "geom public.geometry(MultiPolygon, 4326) NOT NULL",
            metric_twin("geom", "MultiPolygon"),
            "valid_during tstzrange NOT NULL DEFAULT tstzrange(now(), NULL)",
            *audit,
        ],
        [
            "CONSTRAINT pk_device_field_of_view PRIMARY KEY (id)",
            "CONSTRAINT uq_device_field_of_view_id_tenant_id UNIQUE (id, tenant_id)",
            "CONSTRAINT fk_device_field_of_view_tenant_id_tenant FOREIGN KEY (tenant_id) "
            "REFERENCES meta.tenant (tenant_id) ON DELETE RESTRICT",
            "CONSTRAINT fk_device_field_of_view_device_id_tenant_id_device "
            "FOREIGN KEY (device_id, tenant_id) "
            "REFERENCES ops.device (id, tenant_id) ON DELETE CASCADE",
            "CONSTRAINT ck_device_field_of_view_geometry_method "
            "CHECK (geometry_method IN ('modelled', 'surveyed'))",
            "CONSTRAINT ck_device_field_of_view_modelled_parameters CHECK (geometry_method <> 'modelled' OR "
            "(bearing_deg IS NOT NULL AND fov_deg IS NOT NULL AND range_m IS NOT NULL))",
            "CONSTRAINT ck_device_field_of_view_bearing_deg CHECK (bearing_deg >= 0 AND bearing_deg < 360)",
            "CONSTRAINT ck_device_field_of_view_fov_deg CHECK (fov_deg > 0 AND fov_deg <= 360)",
            "CONSTRAINT ck_device_field_of_view_range_m CHECK (range_m > 0 AND range_m <= 10000)",
            "CONSTRAINT ck_device_field_of_view_valid_during CHECK (NOT isempty(valid_during) "
            "AND NOT lower_inf(valid_during))",
            "CONSTRAINT ex_device_field_of_view_device_id_valid_during "
            "EXCLUDE USING gist (device_id WITH =, valid_during WITH &&)",
            geometry_checks("ops.device_field_of_view"),
            *audit_constraints,
        ],
    )
    gist_index("ops.device_field_of_view", "geom")
    gist_index("ops.device_field_of_view", "geom_metric")
    op.execute(
        """
        CREATE FUNCTION ops.model_field_of_view()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            device_position public.geometry;
        BEGIN
            IF NEW.geometry_method = 'modelled' THEN
                -- A closed period keeps the sector it was modelled with, unless its parameters change.
                IF TG_OP = 'UPDATE' AND NOT upper_inf(NEW.valid_during)
                    AND OLD.geometry_method = 'modelled'
                    AND NEW.device_id = OLD.device_id
                    AND NEW.bearing_deg IS NOT DISTINCT FROM OLD.bearing_deg
                    AND NEW.fov_deg IS NOT DISTINCT FROM OLD.fov_deg
                    AND NEW.range_m IS NOT DISTINCT FROM OLD.range_m THEN
                    NEW.geom := OLD.geom;
                    RETURN NEW;
                END IF;
                SELECT d.geom INTO device_position
                FROM ops.device AS d
                WHERE d.id = NEW.device_id AND d.tenant_id = NEW.tenant_id;
                -- An unknown device is reported by the foreign key.
                IF device_position IS NOT NULL THEN
                    NEW.geom := meta.sector_polygon(
                        device_position, NEW.bearing_deg::double precision,
                        NEW.fov_deg::double precision, NEW.range_m::double precision);
                END IF;
            ELSIF NEW.geom IS NOT NULL THEN
                -- PostGIS stores a polygon as a MultiPolygon here; report invalid input clearly.
                IF NOT public.ST_IsValid(NEW.geom, 0) THEN
                    RAISE EXCEPTION 'invalid field-of-view polygon: %', public.ST_IsValidReason(NEW.geom)
                        USING ERRCODE = '22023';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER a20_model_field_of_view BEFORE INSERT OR UPDATE ON ops.device_field_of_view "
        "FOR EACH ROW EXECUTE FUNCTION ops.model_field_of_view()"
    )
    version_trigger("ops.device_field_of_view")
    touch_trigger("ops.device_field_of_view")
    # When a device moves, its open modelled fields of view follow; closed periods keep their geometry.
    # Close the current period before moving a device if the old view must be kept.
    op.execute(
        """
        CREATE FUNCTION ops.refresh_modelled_fields_of_view()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            UPDATE ops.device_field_of_view AS f
            SET updated_by = NEW.updated_by
            WHERE f.device_id = NEW.id
              AND f.geometry_method = 'modelled'
              AND upper_inf(f.valid_during);
            RETURN NULL;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER z10_refresh_fields_of_view AFTER UPDATE OF geom ON ops.device "
        "FOR EACH ROW WHEN (NOT public.ST_Equals(OLD.geom, NEW.geom)) "
        "EXECUTE FUNCTION ops.refresh_modelled_fields_of_view()"
    )
    comment_table(
        "ops.device_field_of_view",
        "Area a camera or sensor observes, per validity period (no overlapping periods per device). "
        "Modelled sectors are computed by the database from the device position.",
    )
    comment_columns(
        "ops.device_field_of_view",
        {
            **AUDIT_COMMENTS,
            "tenant_id": "Owning tenant; always the tenant of the device.",
            "geometry_method": "modelled (sector computed from bearing, angle and range) "
            "or surveyed (supplied).",
            "bearing_deg": "Viewing direction in degrees clockwise from north.",
            "fov_deg": "Horizontal field-of-view angle in degrees (360 for omnidirectional sensors).",
            "range_m": "Effective detection range in metres.",
            "geom": "Field-of-view area, EPSG:4326.",
            "geom_metric": "Stored EPSG:5235 copy of geom.",
            "valid_during": "Period in which this field of view applies.",
        },
    )


def _geofence() -> None:
    tenancy, tenancy_constraints = _tenancy_columns("geofence")
    audit, audit_constraints = _audit_columns("geofence")
    _create(
        "geofence",
        [
            "id uuid NOT NULL DEFAULT uuidv7()",
            *tenancy,
            "external_id text",
            "name text NOT NULL",
            "description text",
            "geofence_kind text NOT NULL",
            "definition_geom public.geometry(Geometry, 4326) NOT NULL",
            metric_twin("definition_geom", "Geometry"),
            "radius_m numeric(10, 2)",
            "geom public.geometry(MultiPolygon, 4326) NOT NULL",
            "geom_metric public.geometry(MultiPolygon, 5235) NOT NULL",
            "area_m2 double precision NOT NULL",
            "status text NOT NULL DEFAULT 'active'",
            "effective_during tstzrange NOT NULL DEFAULT tstzrange(now(), NULL)",
            *audit,
        ],
        [
            "CONSTRAINT pk_geofence PRIMARY KEY (id)",
            "CONSTRAINT uq_geofence_id_tenant_id UNIQUE (id, tenant_id)",
            "CONSTRAINT uq_geofence_tenant_id_external_id UNIQUE (tenant_id, external_id)",
            *tenancy_constraints,
            "CONSTRAINT ck_geofence_geofence_kind CHECK (geofence_kind IN ('polygon', 'circle', 'corridor'))",
            "CONSTRAINT ck_geofence_definition_matches_kind CHECK ("
            "(geofence_kind = 'polygon' "
            "AND public.GeometryType(definition_geom) IN ('POLYGON', 'MULTIPOLYGON') "
            "AND radius_m IS NULL) "
            "OR (geofence_kind = 'circle' AND public.GeometryType(definition_geom) = 'POINT' "
            "AND radius_m > 0 AND radius_m <= 50000) "
            "OR (geofence_kind = 'corridor' AND public.GeometryType(definition_geom) IN "
            "('LINESTRING', 'MULTILINESTRING') AND radius_m > 0 AND radius_m <= 5000))",
            "CONSTRAINT ck_geofence_status CHECK (status IN ('draft', 'active', 'suspended', 'archived'))",
            "CONSTRAINT ck_geofence_effective_during CHECK (NOT isempty(effective_during) "
            "AND NOT lower_inf(effective_during))",
            "CONSTRAINT ck_geofence_area_m2 CHECK (area_m2 > 0)",
            "CONSTRAINT ck_geofence_name_not_blank CHECK (btrim(name) <> '')",
            geometry_checks("ops.geofence", "definition_geom"),
            geometry_checks("ops.geofence", "geom"),
            "CONSTRAINT ck_geofence_geom_metric_valid CHECK (public.ST_IsValid(geom_metric, 0))",
            *audit_constraints,
        ],
    )
    gist_index("ops.geofence", "geom")
    gist_index("ops.geofence", "geom_metric")
    gist_index("ops.geofence", "tenant_id, geom", name="ix_geofence_tenant_id_geom_gist")
    gist_index("ops.geofence", "effective_during")
    op.execute(
        f"""
        CREATE FUNCTION ops.derive_geofence_geometry()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            kind text := public.GeometryType(NEW.definition_geom);
            metric public.geometry;
            circumscribed double precision;
        BEGIN
            -- Geometries are compared as EWKB: exact, NULL-safe and independent of search_path.
            IF TG_OP = 'UPDATE'
                AND public.ST_AsEWKB(NEW.definition_geom)
                    IS NOT DISTINCT FROM public.ST_AsEWKB(OLD.definition_geom)
                AND NEW.geofence_kind IS NOT DISTINCT FROM OLD.geofence_kind
                AND NEW.radius_m IS NOT DISTINCT FROM OLD.radius_m
                AND public.ST_AsEWKB(NEW.geom) IS NOT DISTINCT FROM public.ST_AsEWKB(OLD.geom)
                AND public.ST_AsEWKB(NEW.geom_metric) IS NOT DISTINCT FROM public.ST_AsEWKB(OLD.geom_metric)
                AND NEW.area_m2 IS NOT DISTINCT FROM OLD.area_m2 THEN
                RETURN NEW;
            END IF;
            IF NEW.definition_geom IS NULL OR NEW.geofence_kind IS NULL THEN
                RETURN NEW;  -- NOT NULL constraints report the problem
            END IF;
            IF public.ST_IsEmpty(NEW.definition_geom) THEN
                RAISE EXCEPTION 'geofence definition is empty' USING ERRCODE = '22023';
            END IF;
            IF NOT public.ST_IsValid(NEW.definition_geom, 0) THEN
                RAISE EXCEPTION 'invalid geofence definition: %', public.ST_IsValidReason(NEW.definition_geom)
                    USING ERRCODE = '22023';
            END IF;
            IF NOT meta.is_within_sri_lanka(NEW.definition_geom) THEN
                RAISE EXCEPTION 'geofence definition lies outside the service area' USING ERRCODE = '22023';
            END IF;

            IF NEW.geofence_kind = 'polygon' AND kind IN ('POLYGON', 'MULTIPOLYGON') THEN
                NEW.geom := public.ST_Multi(NEW.definition_geom);
                NEW.geom_metric := public.ST_Multi(public.ST_Transform(NEW.definition_geom, 5235));
                NEW.area_m2 := public.ST_Area(NEW.geom_metric);
            ELSIF NEW.radius_m > 0 AND (
                (NEW.geofence_kind = 'circle' AND kind = 'POINT')
                OR (NEW.geofence_kind = 'corridor' AND kind IN ('LINESTRING', 'MULTILINESTRING'))
            ) THEN
                circumscribed := NEW.radius_m::double precision / cos(pi() / (4 * {QUAD_SEGS}));
                metric := public.ST_Transform(NEW.definition_geom, 5235);
                NEW.geom_metric := public.ST_Multi(
                    public.ST_Buffer(metric, circumscribed, 'quad_segs={QUAD_SEGS}'));
                NEW.geom := public.ST_Multi(public.ST_Transform(NEW.geom_metric, 4326));
                IF NEW.geofence_kind = 'circle' THEN
                    NEW.area_m2 := pi() * power(NEW.radius_m::double precision, 2);
                ELSE
                    NEW.area_m2 := public.ST_Area(
                        public.ST_Buffer(metric, NEW.radius_m::double precision, 'quad_segs={QUAD_SEGS}'));
                END IF;
            ELSE
                RAISE EXCEPTION 'a % geofence cannot be defined by a % with radius %',
                    NEW.geofence_kind, lower(kind), coalesce(NEW.radius_m::text, 'NULL')
                    USING ERRCODE = '22023';
            END IF;
            IF public.ST_IsEmpty(NEW.geom_metric) OR NOT public.ST_IsValid(NEW.geom, 0) THEN
                RAISE EXCEPTION 'geofence geometry could not be derived' USING ERRCODE = '22023';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER a20_derive_geometry BEFORE INSERT OR UPDATE ON ops.geofence "
        "FOR EACH ROW EXECUTE FUNCTION ops.derive_geofence_geometry()"
    )
    version_trigger("ops.geofence")
    touch_trigger("ops.geofence")
    comment_table(
        "ops.geofence",
        "Tenant geofences: polygons, circles (point + radius) and corridors (line + half-width). "
        "Search geometries are derived by the database.",
    )
    comment_columns(
        "ops.geofence",
        {
            **TENANCY_COMMENTS,
            "external_id": "Identifier of the geofence in the tenant's own systems.",
            "geofence_kind": "polygon, circle or corridor.",
            "definition_geom": "Geometry as defined by the user, EPSG:4326: polygon, circle centre or "
            "corridor centre line.",
            "definition_geom_metric": "Stored EPSG:5235 copy of definition_geom; circle and corridor hits "
            "are ST_DWithin(definition_geom_metric, point, radius_m), boundary inclusive.",
            "radius_m": "Circle radius or corridor half-width in metres.",
            "geom": "Area as an EPSG:4326 MultiPolygon (display, bounding-box search).",
            "geom_metric": "Search area in EPSG:5235. For circles and corridors it circumscribes the exact "
            f"buffer (quad_segs={QUAD_SEGS}); for polygons it is the transformed definition.",
            "area_m2": "Area in square metres (exact for circles).",
            "status": "draft, active, suspended or archived. Only active geofences produce hits.",
            "effective_during": "Period in which the geofence produces hits.",
        },
    )


LAYERS = (
    ("ops.site", "Sites", "Installation sites.", ("POINT",), "private", 5.0),
    ("ops.device", "Devices", "Cameras and sensors.", ("POINT",), "private", 5.0),
    (
        "ops.device_field_of_view",
        "Device fields of view",
        "Areas observed by cameras and sensors.",
        ("MULTIPOLYGON",),
        "private",
        10.0,
    ),
    ("ops.geofence", "Geofences", "Tenant geofences.", ("MULTIPOLYGON",), "private", None),
)


def upgrade() -> None:
    _site()
    _device()
    _field_of_view()
    _geofence()
    for table in ("site", "device", "geofence"):
        tenant_policies(f"ops.{table}", SHARED_READ)
    tenant_policies("ops.device_field_of_view", DEVICE_READ)
    for code, name, description, geometry_types, sharing, accuracy in LAYERS:
        register_layer(
            code=code,
            name=name,
            description=description,
            layer_group="operational",
            geometry_types=geometry_types,
            tenant_scoped=True,
            default_sharing_policy=sharing,
            update_frequency="on_change",
            nominal_accuracy_m=accuracy,
        )


def downgrade() -> None:
    refuse_if_not_empty([layer[0] for layer in LAYERS])
    unregister_layers([layer[0] for layer in LAYERS])
    op.execute("DROP TABLE ops.geofence")
    op.execute("DROP FUNCTION ops.derive_geofence_geometry()")
    op.execute("DROP TABLE ops.device_field_of_view")
    op.execute("DROP TABLE ops.device")
    op.execute("DROP FUNCTION ops.refresh_modelled_fields_of_view()")
    op.execute("DROP FUNCTION ops.model_field_of_view()")
    op.execute("DROP TABLE ops.site")
