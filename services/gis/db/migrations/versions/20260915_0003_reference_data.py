"""Reference data layers (schema ``ref``).

National reference geodata, loaded into versioned releases (``meta.ref_data_release``) and read-only for
the API:

* ``ref.admin_area``      administrative hierarchy: country, province, district, DS division, GN division
* ``ref.settlement``      cities, towns and villages (point, or footprint polygon)
* ``ref.facility``        police stations, hospitals, wildlife offices and other facilities
* ``ref.road``            road network (E/A/B/C/D classes, local roads, tracks)
* ``ref.water_body``      rivers and canals (lines), reservoirs, lakes and lagoons (polygons)
* ``ref.protected_area``  national parks, sanctuaries, forest reserves
* ``ref.risk_zone``       elephant corridors, flood, landslide and other hazard zones
* ``ref.area_part``       subdivided polygons of the area layers, maintained by triggers for fast
                          point-in-polygon lookups (never written directly)

Every layer stores the canonical geometry in EPSG:4326 (``geom``) and a stored EPSG:5235 twin
(``geom_metric``) for distances, buffers and nearest-neighbour searches, with the geometry source and
accuracy, the release, the load (lineage) and timestamps.

Revision ID: 20260915_0003
Revises: 20260915_0002
Create Date: 2026-09-15 00:00:02+00:00
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import NamedTuple

from alembic import op
from migration_support import (
    comment_columns,
    comment_table,
    geometry_checks,
    gist_index,
    metric_twin,
    refuse_if_not_empty,
    register_layer,
    touch_trigger,
    unregister_layers,
)

revision: str = "20260915_0003"
down_revision: str | Sequence[str] | None = "20260915_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GEOMETRY_SOURCES = ("survey", "gps", "digitised", "imagery", "osm", "derived", "synthetic", "unknown")
AREA_KINDS = ("admin_area", "protected_area", "risk_zone", "water_body")

COMMON_COLUMN_COMMENTS = {
    "release_id": "Reference data release this row belongs to.",
    "load_id": "Dataset load (lineage) that produced this row.",
    "source_feature_id": "Identifier of the feature in the source dataset.",
    "name_si": "Name in Sinhala.",
    "name_ta": "Name in Tamil.",
    "geom": "Canonical geometry, EPSG:4326 (longitude, latitude).",
    "geom_metric": "Stored EPSG:5235 (SLD99 / Sri Lanka Grid 1999) copy of geom for metric operations.",
    "geometry_source": "How the geometry was captured: " + ", ".join(GEOMETRY_SOURCES) + ".",
    "geometry_accuracy_m": "Estimated horizontal accuracy of the geometry in metres.",
    "attributes": "Additional source attributes (JSON object).",
}


def _in(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Layer(NamedTuple):
    code: str
    name: str
    description: str
    geometry_types: tuple[str, ...]
    nominal_accuracy_m: float


# NamedTuple rather than dataclass: Alembic loads revision files without registering them in sys.modules.
class ReferenceTable(NamedTuple):
    name: str
    geometry_type: str
    columns: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    name_required: bool = True
    normalise_geometry: bool = True
    area_kind: str | None = None
    comment: str = ""
    column_comments: Mapping[str, str] = MappingProxyType({})
    extra_indexes: tuple[str, ...] = ()

    @property
    def qualified(self) -> str:
        return f"ref.{self.name}"


def _create(table: ReferenceTable) -> None:
    name = table.name
    columns = [
        "id uuid NOT NULL DEFAULT uuidv7()",
        "release_id uuid NOT NULL",
        "load_id uuid NOT NULL",
        "source_feature_id text",
        f"name text{' NOT NULL' if table.name_required else ''}",
        "name_si text",
        "name_ta text",
        *table.columns,
        f"geom public.geometry({table.geometry_type}, 4326) NOT NULL",
        metric_twin("geom", table.geometry_type),
        "geometry_source text NOT NULL DEFAULT 'unknown'",
        "geometry_accuracy_m numeric(10, 2)",
        "attributes jsonb NOT NULL DEFAULT '{}'::jsonb",
        "created_at timestamptz NOT NULL DEFAULT now()",
        "updated_at timestamptz NOT NULL DEFAULT now()",
    ]
    constraints = [
        f"CONSTRAINT pk_{name} PRIMARY KEY (id)",
        f"CONSTRAINT uq_{name}_id_release_id UNIQUE (id, release_id)",
        f"CONSTRAINT uq_{name}_release_id_source_feature_id UNIQUE (release_id, source_feature_id)",
        f"CONSTRAINT fk_{name}_load_id_release_id_dataset_load FOREIGN KEY (load_id, release_id) "
        "REFERENCES meta.dataset_load (id, release_id) ON DELETE CASCADE",
        f"CONSTRAINT ck_{name}_geometry_source CHECK (geometry_source IN ({_in(GEOMETRY_SOURCES)}))",
        f"CONSTRAINT ck_{name}_geometry_accuracy_m CHECK (geometry_accuracy_m > 0)",
        f"CONSTRAINT ck_{name}_attributes_is_object CHECK (jsonb_typeof(attributes) = 'object')",
        geometry_checks(table.qualified),
        *table.constraints,
    ]
    if table.name_required:
        constraints.append(f"CONSTRAINT ck_{name}_name_not_blank CHECK (btrim(name) <> '')")
    body = ",\n    ".join(columns + constraints)
    op.execute(f"CREATE TABLE {table.qualified} (\n    {body}\n)")

    gist_index(table.qualified, "release_id, geom", name=f"ix_{name}_release_id_geom_gist")
    gist_index(table.qualified, "release_id, geom_metric", name=f"ix_{name}_release_id_geom_metric_gist")
    op.execute(f"CREATE INDEX ix_{name}_load_id ON {table.qualified} (load_id)")
    for statement in table.extra_indexes:
        op.execute(statement)

    op.execute(
        f"CREATE TRIGGER a10_guard_release_is_draft BEFORE INSERT OR UPDATE OR DELETE ON {table.qualified} "
        "FOR EACH ROW EXECUTE FUNCTION meta.guard_release_is_draft()"
    )
    if table.normalise_geometry:
        op.execute(
            f"CREATE TRIGGER a20_normalise_geometry BEFORE INSERT OR UPDATE OF geom ON {table.qualified} "
            "FOR EACH ROW EXECUTE FUNCTION meta.normalise_reference_geometry()"
        )
    touch_trigger(table.qualified)
    if table.area_kind is not None:
        op.execute(
            f"CREATE TRIGGER z10_sync_area_part AFTER INSERT OR UPDATE OF geom, release_id OR DELETE "
            f"ON {table.qualified} FOR EACH ROW EXECUTE FUNCTION ref.sync_area_part('{table.area_kind}')"
        )

    comment_table(table.qualified, table.comment)
    comment_columns(table.qualified, {**COMMON_COLUMN_COMMENTS, **table.column_comments})


TABLES: tuple[ReferenceTable, ...] = (
    ReferenceTable(
        name="admin_area",
        geometry_type="MultiPolygon",
        area_kind="admin_area",
        columns=(
            "level smallint NOT NULL",
            "level_name text GENERATED ALWAYS AS (CASE level WHEN 0 THEN 'country' WHEN 1 THEN 'province' "
            "WHEN 2 THEN 'district' WHEN 3 THEN 'ds_division' WHEN 4 THEN 'gn_division' END) STORED",
            "code text NOT NULL",
            "parent_id uuid",
        ),
        constraints=(
            "CONSTRAINT uq_admin_area_release_id_level_code UNIQUE (release_id, level, code)",
            # NO ACTION (checked at the end of the statement) so that a whole release can be deleted.
            "CONSTRAINT fk_admin_area_parent_id_release_id_admin_area FOREIGN KEY (parent_id, release_id) "
            "REFERENCES ref.admin_area (id, release_id)",
            "CONSTRAINT ck_admin_area_level CHECK (level BETWEEN 0 AND 4)",
            "CONSTRAINT ck_admin_area_parent_required CHECK (level <= 1 OR parent_id IS NOT NULL)",
            "CONSTRAINT ck_admin_area_country_has_no_parent CHECK (level > 0 OR parent_id IS NULL)",
            "CONSTRAINT ck_admin_area_code_not_blank CHECK (btrim(code) <> '')",
        ),
        extra_indexes=("CREATE INDEX ix_admin_area_parent_id ON ref.admin_area (parent_id)",),
        comment="Administrative areas of Sri Lanka: level 0 country, 1 province, 2 district, "
        "3 divisional secretariat (DS) division, 4 Grama Niladhari (GN) division.",
        column_comments={
            "level": "0 country, 1 province, 2 district, 3 DS division, 4 GN division.",
            "code": "Official or P-code of the area, unique per level within a release.",
            "parent_id": "Containing area one level up, in the same release. Optional for provinces.",
        },
    ),
    ReferenceTable(
        name="settlement",
        geometry_type="Geometry",
        columns=(
            "settlement_type text NOT NULL",
            "population integer",
            "population_year smallint",
            "admin_area_id uuid",
            "geometry_basis text GENERATED ALWAYS AS (CASE WHEN public.GeometryType(geom) = 'POINT' "
            "THEN 'point' ELSE 'footprint' END) STORED",
            "label_point public.geometry(Point, 4326) GENERATED ALWAYS AS ("
            "CASE WHEN public.GeometryType(geom) = 'POINT' THEN geom "
            "ELSE public.ST_PointOnSurface(geom) END) STORED",
        ),
        constraints=(
            "CONSTRAINT fk_settlement_admin_area_id_release_id_admin_area "
            "FOREIGN KEY (admin_area_id, release_id) "
            "REFERENCES ref.admin_area (id, release_id)",
            "CONSTRAINT ck_settlement_geometry_type "
            "CHECK (public.GeometryType(geom) IN ('POINT', 'MULTIPOLYGON'))",
            "CONSTRAINT ck_settlement_settlement_type CHECK (settlement_type IN "
            "('capital', 'city', 'town', 'village', 'estate', 'hamlet', 'other'))",
            "CONSTRAINT ck_settlement_population CHECK (population >= 0)",
            "CONSTRAINT ck_settlement_population_year CHECK (population_year BETWEEN 1800 AND 2200)",
        ),
        extra_indexes=("CREATE INDEX ix_settlement_admin_area_id ON ref.settlement (admin_area_id)",),
        comment="Populated places. A settlement is a point (place node) or a footprint polygon; "
        "nearest-settlement distances are measured to the footprint edge (0 inside).",
        column_comments={
            "geometry_basis": "point or footprint, derived from the geometry type.",
            "label_point": "Point for labels: the point itself, or a point on the footprint surface.",
            "admin_area_id": "Lowest administrative area known to contain the settlement.",
        },
    ),
    ReferenceTable(
        name="facility",
        geometry_type="Point",
        normalise_geometry=False,
        columns=("facility_type text NOT NULL",),
        constraints=(
            "CONSTRAINT ck_facility_facility_type CHECK (facility_type IN ('police_station', 'hospital', "
            "'school', 'fire_station', 'wildlife_office', 'forest_office', 'government_office', "
            "'place_of_worship', 'other'))",
        ),
        extra_indexes=(
            "CREATE INDEX ix_facility_release_id_facility_type ON ref.facility (release_id, facility_type)",
        ),
        comment="Public facilities used as geographic context "
        "(police stations, hospitals, wildlife offices, ...).",
    ),
    ReferenceTable(
        name="road",
        geometry_type="MultiLineString",
        name_required=False,
        columns=(
            "road_class text NOT NULL DEFAULT 'unknown'",
            "ref_code text",
            "osm_highway text",
        ),
        constraints=(
            "CONSTRAINT ck_road_road_class CHECK (road_class IN "
            "('E', 'A', 'B', 'C', 'D', 'local', 'track', 'unknown'))",
        ),
        comment="Road network. road_class follows the RDA classification (E expressways, A/B national, "
        "C/D provincial) plus local roads and tracks.",
        column_comments={
            "ref_code": "Route number, e.g. A9 or E01.",
            "osm_highway": "OpenStreetMap highway tag of the source feature, where applicable.",
        },
    ),
    ReferenceTable(
        name="water_body",
        geometry_type="Geometry",
        name_required=False,
        area_kind="water_body",
        columns=(
            "water_type text NOT NULL",
            "geometry_kind text GENERATED ALWAYS AS (CASE WHEN public.GeometryType(geom) = 'MULTILINESTRING' "
            "THEN 'line' ELSE 'area' END) STORED",
        ),
        constraints=(
            "CONSTRAINT ck_water_body_geometry_type "
            "CHECK (public.GeometryType(geom) IN ('MULTILINESTRING', 'MULTIPOLYGON'))",
            "CONSTRAINT ck_water_body_water_type CHECK (water_type IN "
            "('river', 'stream', 'canal', 'reservoir', 'tank', 'lake', 'lagoon', 'wetland', 'other'))",
        ),
        comment="Rivers, streams and canals (lines); "
        "reservoirs, tanks, lakes, lagoons and wetlands (polygons).",
        column_comments={"geometry_kind": "line or area, derived from the geometry type."},
    ),
    ReferenceTable(
        name="protected_area",
        geometry_type="MultiPolygon",
        area_kind="protected_area",
        columns=(
            "designation text NOT NULL",
            "managing_authority text NOT NULL",
            "iucn_category text",
            "designated_on date",
        ),
        constraints=(
            "CONSTRAINT ck_protected_area_managing_authority "
            "CHECK (managing_authority IN ('DWC', 'FD', 'CCD', 'other'))",
            "CONSTRAINT ck_protected_area_iucn_category CHECK (iucn_category IN "
            "('Ia', 'Ib', 'II', 'III', 'IV', 'V', 'VI', 'not_reported', 'not_applicable', 'not_assigned'))",
        ),
        comment="Protected areas: national parks, sanctuaries, nature reserves, forest reserves.",
        column_comments={
            "designation": "Legal designation, e.g. National Park, Sanctuary, Forest Reserve.",
            "managing_authority": "DWC (Department of Wildlife Conservation), FD (Forest Department), "
            "CCD (Coast Conservation Department) or other.",
        },
    ),
    ReferenceTable(
        name="risk_zone",
        geometry_type="MultiPolygon",
        area_kind="risk_zone",
        columns=(
            "risk_type text NOT NULL",
            "severity smallint NOT NULL",
            "valid_during tstzrange NOT NULL DEFAULT tstzrange(NULL, NULL)",
        ),
        constraints=(
            "CONSTRAINT ck_risk_zone_risk_type CHECK (risk_type IN "
            "('elephant_corridor', 'flood', 'landslide', 'tsunami', 'cyclone', 'drought', 'other'))",
            "CONSTRAINT ck_risk_zone_severity CHECK (severity BETWEEN 1 AND 5)",
            "CONSTRAINT ck_risk_zone_valid_during_not_empty CHECK (NOT isempty(valid_during))",
        ),
        extra_indexes=(
            "CREATE INDEX ix_risk_zone_valid_during_gist ON ref.risk_zone USING gist (valid_during)",
        ),
        comment="Hazard and risk zones (elephant corridors, flood, landslide, ...) "
        "with severity and validity.",
        column_comments={
            "severity": "1 (low) to 5 (very high), as assigned by the publishing authority.",
            "valid_during": "Period in which the zone applies; unbounded by default.",
        },
    ),
)

LAYERS: tuple[Layer, ...] = (
    Layer(
        "ref.admin_area",
        "Administrative areas",
        "Province, district, DS division and GN division boundaries.",
        ("MULTIPOLYGON",),
        50,
    ),
    Layer(
        "ref.settlement",
        "Settlements",
        "Cities, towns and villages as points or footprints.",
        (
            "POINT",
            "MULTIPOLYGON",
        ),
        100,
    ),
    Layer(
        "ref.facility",
        "Facilities",
        "Police stations, hospitals, wildlife and forest offices and other facilities.",
        ("POINT",),
        25,
    ),
    Layer("ref.road", "Roads", "Road network by RDA class.", ("MULTILINESTRING",), 20),
    Layer(
        "ref.water_body",
        "Rivers and water bodies",
        "Rivers, canals, reservoirs, tanks, lakes and lagoons.",
        (
            "MULTILINESTRING",
            "MULTIPOLYGON",
        ),
        50,
    ),
    Layer(
        "ref.protected_area",
        "Protected areas",
        "National parks, sanctuaries and forest reserves.",
        ("MULTIPOLYGON",),
        50,
    ),
    Layer(
        "ref.risk_zone", "Risk zones", "Elephant corridors and natural hazard zones.", ("MULTIPOLYGON",), 100
    ),
)


def _area_part() -> None:
    op.execute(
        f"""
        CREATE TABLE ref.area_part (
            id bigint GENERATED ALWAYS AS IDENTITY,
            release_id uuid NOT NULL,
            area_kind text NOT NULL,
            feature_id uuid NOT NULL,
            geom public.geometry(Polygon, 4326) NOT NULL,
            CONSTRAINT pk_area_part PRIMARY KEY (id),
            CONSTRAINT ck_area_part_area_kind CHECK (area_kind IN ({_in(AREA_KINDS)}))
        )
        """
    )
    gist_index(
        "ref.area_part", "release_id, area_kind, geom", name="ix_area_part_release_id_area_kind_geom_gist"
    )
    op.execute("CREATE INDEX ix_area_part_feature_id ON ref.area_part (feature_id)")
    comment_table(
        "ref.area_part",
        "Polygons of the area layers split with ST_Subdivide (at most 255 vertices each), so that "
        "point-in-polygon tests touch small geometries. Maintained by triggers; do not write directly.",
    )
    comment_columns(
        "ref.area_part",
        {
            "area_kind": "Source table: " + ", ".join(AREA_KINDS) + ".",
            "feature_id": "id of the source row in ref.<area_kind>.",
            "geom": "Part of the source geometry, EPSG:4326 (containment is evaluated in the canonical CRS).",
        },
    )
    op.execute(
        """
        CREATE FUNCTION ref.sync_area_part()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                DELETE FROM ref.area_part WHERE feature_id = OLD.id;
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE') AND public.GeometryType(NEW.geom) = 'MULTIPOLYGON' THEN
                INSERT INTO ref.area_part (release_id, area_kind, feature_id, geom)
                SELECT NEW.release_id, TG_ARGV[0], NEW.id, part.geom
                FROM public.ST_Subdivide(NEW.geom, 255) AS piece(geom)
                CROSS JOIN LATERAL public.ST_Dump(piece.geom) AS part;
            END IF;
            RETURN NULL;
        END
        $$
        """
    )


def _admin_hierarchy_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION ref.check_admin_area_parent()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            parent_level smallint;
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW.level <> OLD.level
                AND EXISTS (SELECT 1 FROM ref.admin_area AS c WHERE c.parent_id = OLD.id) THEN
                RAISE EXCEPTION 'admin area % has child areas; its level cannot change', OLD.code
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.parent_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT p.level INTO parent_level
            FROM ref.admin_area AS p
            WHERE p.id = NEW.parent_id AND p.release_id = NEW.release_id;
            -- A missing parent is reported by the foreign key.
            IF parent_level IS NOT NULL AND parent_level <> NEW.level - 1 THEN
                RAISE EXCEPTION 'admin area % (level %) cannot have a level % parent',
                    NEW.code, NEW.level, parent_level
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER a30_check_parent BEFORE INSERT OR UPDATE OF parent_id, level, release_id "
        "ON ref.admin_area FOR EACH ROW EXECUTE FUNCTION ref.check_admin_area_parent()"
    )


def upgrade() -> None:
    _area_part()
    for table in TABLES:
        _create(table)
        if table.name == "admin_area":
            _admin_hierarchy_guard()
    for layer in LAYERS:
        register_layer(
            code=layer.code,
            name=layer.name,
            description=layer.description,
            layer_group="reference",
            geometry_types=layer.geometry_types,
            tenant_scoped=False,
            default_sharing_policy=None,
            update_frequency="release",
            nominal_accuracy_m=layer.nominal_accuracy_m,
        )


def downgrade() -> None:
    refuse_if_not_empty([table.qualified for table in TABLES])
    unregister_layers([layer.code for layer in LAYERS])
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table.qualified}")
    op.execute("DROP FUNCTION ref.check_admin_area_parent()")
    op.execute("DROP TABLE ref.area_part")
    op.execute("DROP FUNCTION ref.sync_area_part()")
