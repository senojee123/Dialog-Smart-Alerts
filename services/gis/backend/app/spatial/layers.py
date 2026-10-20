"""The layers the query API exposes, and the only SQL identifiers its statements contain.

Every statement the spatial query repository builds takes its schema, table, column and expression
names from this module. A request selects a layer, a filter or a property *by name*; the name is looked
up here and the constant found is what reaches SQL. Values always travel as bound parameters, so no
client input is ever interpolated into a statement (ARCHITECTURE.md, "SQL and query safety").

Two scopes:

* ``release`` - national reference data in ``ref``, immutable per reference data release. Every query
  names a release (the current one by default) and answers carry ``refDataRelease``.
* ``tenant`` - operational data in ``ops`` and events in ``geo``, protected by row-level security. The
  tenant of the transaction decides what is visible; queries additionally state the bounding-box test
  (``&&``) so that PostgreSQL can use the spatial index (see ADR-0014).

Layers are addressed by their registry code (``meta.layer.code``, e.g. ``ref.settlement``), which is also
the table's qualified name. ``meta.layer`` stays the authority for what exists and is published; this
module decides what may be *queried* and which columns are exposed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Literal

Scope = Literal["release", "tenant"]
GeometryKind = Literal["point", "line", "area"]
FilterKind = Literal["text", "int", "uuid"]
Capability = Literal["features", "within_distance", "nearest", "contains"]

# Accepted CRS identifiers for the optional ``crs`` member: GeoJSON is always WGS84 (RFC 7946).
CRS_ALIASES: Final = frozenset(
    {
        "epsg:4326",
        "crs84",
        "wgs84",
        "ogc:1.3:crs84",
        "urn:ogc:def:crs:ogc::crs84",
        "urn:ogc:def:crs:epsg::4326",
    }
)
CANONICAL_CRS: Final = "EPSG:4326"


@dataclass(frozen=True, slots=True)
class Property:
    """A feature property: the JSON key clients see and the SQL expression that produces it."""

    key: str
    expression: str


@dataclass(frozen=True, slots=True)
class ValueFilter:
    """An equality filter on a whitelisted column, with the values it accepts where they are enumerated."""

    name: str
    column: str
    kind: FilterKind = "text"
    values: tuple[str, ...] = ()

    @property
    def parameter(self) -> str:
        return f"f_{self.name}"

    @property
    def cast(self) -> str:
        return {"text": "text", "int": "integer", "uuid": "uuid"}[self.kind]


def _p(key: str, expression: str | None = None) -> Property:
    return Property(key=key, expression=expression or f"t.{_snake(key)}")


def _snake(key: str) -> str:
    return "".join(f"_{char.lower()}" if char.isupper() else char for char in key)


def _period(name: str) -> tuple[Property, Property]:
    """A validity period as two instants; ranges have no JSON representation of their own."""
    return (
        _p(f"{_prefix(name)}From", f"lower(t.{name})"),
        _p(f"{_prefix(name)}To", f"upper(t.{name})"),
    )


def _prefix(name: str) -> str:
    return {"valid_during": "valid", "effective_during": "effective"}[name]


Containment = Literal["geometry", "area_part", "geofence"]


@dataclass(frozen=True, slots=True)
class SpatialLayer:
    code: str
    scope: Scope
    geometry_kinds: frozenset[GeometryKind]
    properties: tuple[Property, ...]
    name_column: str | None = "name"
    category: ValueFilter | None = None
    status: ValueFilter | None = None
    filters: tuple[ValueFilter, ...] = ()
    period_column: str | None = None
    geometry_column: str = "geom"
    metric_column: str = "geom_metric"
    # Circles and corridors are stored as a definition plus a radius; the exact tests use them.
    definition_column: str | None = None
    radius_column: str | None = None
    id_column: str = "id"
    # ``area_part`` layers have their polygons subdivided into ref.area_part, which is what containment
    # searches them through (small, indexed pieces instead of one large polygon).
    area_kind: str | None = None
    containment: Containment = "geometry"
    # Distance to the feature as it is defined: the stored geometry, except for geofences, where a circle
    # or corridor is a definition plus a radius and its search polygon only circumscribes it.
    distance_expression: str | None = None

    @property
    def table(self) -> str:
        return self.code

    @property
    def schema(self) -> str:
        return self.code.split(".", 1)[0]

    @property
    def areal(self) -> bool:
        return "area" in self.geometry_kinds

    def distance_to(self, other: str) -> str:
        """SQL for the distance in metres between this layer's feature (alias ``t``) and ``other``."""
        if self.distance_expression is not None:
            return self.distance_expression.format(other=other)
        return f"public.ST_Distance(t.{self.metric_column}, {other})"

    @property
    def knn_ordered(self) -> bool:
        """Whether nearest-first ordering can use the KNN operator on the indexed geometry."""
        return self.distance_expression is None

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        capabilities: list[Capability] = ["features", "within_distance", "nearest"]
        if self.areal:
            capabilities.append("contains")
        return tuple(capabilities)

    def filter_named(self, name: str) -> ValueFilter | None:
        for value_filter in (self.category, self.status, *self.filters):
            if value_filter is not None and value_filter.name == name:
                return value_filter
        return None

    @property
    def all_filters(self) -> tuple[ValueFilter, ...]:
        return tuple(f for f in (self.category, self.status, *self.filters) if f is not None)

    @property
    def property_keys(self) -> tuple[str, ...]:
        return tuple(prop.key for prop in self.properties)


SETTLEMENT_TYPES: Final = ("capital", "city", "town", "village", "estate", "hamlet", "other")
_FACILITY_TYPES: Final = (
    "police_station",
    "hospital",
    "school",
    "fire_station",
    "wildlife_office",
    "forest_office",
    "government_office",
    "place_of_worship",
    "other",
)
_ROAD_CLASSES: Final = ("E", "A", "B", "C", "D", "local", "track", "unknown")
_WATER_TYPES: Final = ("river", "stream", "canal", "reservoir", "tank", "lake", "lagoon", "wetland", "other")
_RISK_TYPES: Final = ("elephant_corridor", "flood", "landslide", "tsunami", "cyclone", "drought", "other")
SITE_TYPES: Final = ("pole", "building", "junction", "checkpoint", "estate", "perimeter", "other")
DEVICE_TYPES: Final = (
    "camera",
    "anpr_camera",
    "acoustic_sensor",
    "seismic_sensor",
    "environmental_sensor",
    "gateway",
    "other",
)
GEOFENCE_KINDS: Final = ("polygon", "circle", "corridor")
GEOFENCE_STATUSES: Final = ("draft", "active", "suspended", "archived")
SITE_STATUSES: Final = ("planned", "active", "decommissioned")
DEVICE_STATUSES: Final = ("planned", "active", "inactive", "decommissioned")

_TENANCY: Final = (
    _p("tenantId"),
    _p("externalId"),
    _p("sharingPolicy"),
    _p("version"),
    _p("updatedAt"),
)

LAYERS: Final[tuple[SpatialLayer, ...]] = (
    SpatialLayer(
        code="ref.admin_area",
        scope="release",
        geometry_kinds=frozenset({"area"}),
        properties=(
            _p("name"),
            _p("nameSi"),
            _p("nameTa"),
            _p("code"),
            _p("level"),
            _p("levelName"),
            _p("parentId"),
        ),
        filters=(
            ValueFilter("level", "level", "int"),
            ValueFilter("code", "code"),
            ValueFilter("parentId", "parent_id", "uuid"),
        ),
        area_kind="admin_area",
        containment="area_part",
    ),
    SpatialLayer(
        code="ref.settlement",
        scope="release",
        geometry_kinds=frozenset({"point", "area"}),
        properties=(
            _p("name"),
            _p("nameSi"),
            _p("nameTa"),
            _p("settlementType"),
            _p("population"),
            _p("populationYear"),
            _p("basis", "t.geometry_basis"),
            _p("adminAreaId"),
        ),
        category=ValueFilter("type", "settlement_type", values=SETTLEMENT_TYPES),
        filters=(ValueFilter("adminAreaId", "admin_area_id", "uuid"),),
    ),
    SpatialLayer(
        code="ref.facility",
        scope="release",
        geometry_kinds=frozenset({"point"}),
        properties=(_p("name"), _p("nameSi"), _p("nameTa"), _p("facilityType")),
        category=ValueFilter("type", "facility_type", values=_FACILITY_TYPES),
    ),
    SpatialLayer(
        code="ref.road",
        scope="release",
        geometry_kinds=frozenset({"line"}),
        properties=(_p("name"), _p("class", "t.road_class"), _p("refCode"), _p("osmHighway")),
        category=ValueFilter("type", "road_class", values=_ROAD_CLASSES),
        filters=(ValueFilter("refCode", "ref_code"),),
    ),
    SpatialLayer(
        code="ref.water_body",
        scope="release",
        geometry_kinds=frozenset({"line", "area"}),
        properties=(_p("name"), _p("waterType"), _p("geometryKind")),
        category=ValueFilter("type", "water_type", values=_WATER_TYPES),
        area_kind="water_body",
        containment="area_part",
    ),
    SpatialLayer(
        code="ref.protected_area",
        scope="release",
        geometry_kinds=frozenset({"area"}),
        properties=(
            _p("name"),
            _p("designation"),
            _p("managingAuthority"),
            _p("iucnCategory"),
            _p("designatedOn"),
        ),
        category=ValueFilter("type", "designation"),
        filters=(
            ValueFilter("managingAuthority", "managing_authority", values=("DWC", "FD", "CCD", "other")),
        ),
        area_kind="protected_area",
        containment="area_part",
    ),
    SpatialLayer(
        code="ref.risk_zone",
        scope="release",
        geometry_kinds=frozenset({"area"}),
        properties=(_p("name"), _p("riskType"), _p("severity"), *_period("valid_during")),
        category=ValueFilter("type", "risk_type", values=_RISK_TYPES),
        filters=(ValueFilter("severity", "severity", "int"),),
        period_column="valid_during",
        area_kind="risk_zone",
        containment="area_part",
    ),
    SpatialLayer(
        code="ops.site",
        scope="tenant",
        geometry_kinds=frozenset({"point"}),
        properties=(
            _p("name"),
            _p("siteType"),
            _p("status"),
            *_TENANCY,
            _p("positionSource"),
            _p("positionAccuracyM", "t.position_accuracy_m"),
        ),
        category=ValueFilter("type", "site_type", values=SITE_TYPES),
        status=ValueFilter("status", "status", values=SITE_STATUSES),
    ),
    SpatialLayer(
        code="ops.device",
        scope="tenant",
        geometry_kinds=frozenset({"point"}),
        properties=(
            _p("name"),
            _p("deviceType"),
            _p("status"),
            *_TENANCY,
            _p("siteId"),
            _p("mountingHeightM", "t.mounting_height_m"),
            _p("positionSource"),
            _p("positionAccuracyM", "t.position_accuracy_m"),
            _p("installedAt"),
            _p("decommissionedAt"),
        ),
        category=ValueFilter("type", "device_type", values=DEVICE_TYPES),
        status=ValueFilter("status", "status", values=DEVICE_STATUSES),
        filters=(ValueFilter("siteId", "site_id", "uuid"),),
    ),
    SpatialLayer(
        code="ops.device_field_of_view",
        scope="tenant",
        geometry_kinds=frozenset({"area"}),
        properties=(
            _p("deviceId"),
            _p("tenantId"),
            _p("geometryMethod"),
            _p("bearingDeg", "t.bearing_deg"),
            _p("fovDeg", "t.fov_deg"),
            _p("rangeM", "t.range_m"),
            *_period("valid_during"),
            _p("version"),
        ),
        name_column=None,
        filters=(
            ValueFilter("deviceId", "device_id", "uuid"),
            ValueFilter("geometryMethod", "geometry_method", values=("modelled", "surveyed")),
        ),
        period_column="valid_during",
    ),
    SpatialLayer(
        code="ops.geofence",
        scope="tenant",
        geometry_kinds=frozenset({"area"}),
        properties=(
            _p("name"),
            _p("description"),
            _p("geofenceKind"),
            _p("status"),
            _p("radiusM", "t.radius_m"),
            _p("areaM2", "t.area_m2"),
            *_TENANCY,
            *_period("effective_during"),
        ),
        category=ValueFilter("type", "geofence_kind", values=GEOFENCE_KINDS),
        status=ValueFilter("status", "status", values=GEOFENCE_STATUSES),
        period_column="effective_during",
        definition_column="definition_geom",
        radius_column="radius_m",
        containment="geofence",
        # A circle or corridor is a definition plus a radius: the exact distance is measured to the
        # definition and reduced by the radius (0 inside). geom_metric only circumscribes that area.
        distance_expression=(
            "CASE WHEN t.radius_m IS NULL THEN public.ST_Distance(t.geom_metric, {other})"
            " ELSE greatest(public.ST_Distance(t.definition_geom_metric, {other})"
            " - t.radius_m::double precision, 0) END"
        ),
    ),
)

LAYERS_BY_CODE: Final[dict[str, SpatialLayer]] = {layer.code: layer for layer in LAYERS}
LAYER_CODES: Final = tuple(LAYERS_BY_CODE)
# A layer code is a path segment; the pattern documents the shape, the registry decides what exists.
LAYER_CODE_PATTERN: Final = r"^(ref|ops)\.[a-z][a-z0-9_]{1,62}$"
AREAL_LAYER_CODES: Final = tuple(layer.code for layer in LAYERS if layer.areal)
TENANT_LAYER_CODES: Final = tuple(layer.code for layer in LAYERS if layer.scope == "tenant")


@dataclass(frozen=True, slots=True)
class EventFields:
    """Columns of ``geo.event_location`` and ``geo.event_geo_context`` the event query exposes."""

    table: str = "geo.event_location"
    context_table: str = "geo.event_geo_context"
    geofence_hit_table: str = "geo.event_geofence_hit"
    geometry_column: str = "geom"
    metric_column: str = "geom_metric"
    properties: tuple[Property, ...] = (
        _p("eventId"),
        _p("tenantId"),
        _p("observedAt"),
        _p("eventType"),
        _p("eventSubtype"),
        _p("sourceType"),
        _p("deviceId"),
        _p("sourceRef"),
        _p("locationSource"),
        _p("geometryKind"),
        _p("locationAccuracyM", "t.location_accuracy_m"),
        _p("receivedAt"),
    )
    # Administrative filtering uses the columns the enrichment engine stored (indexed per tenant).
    admin_columns: tuple[str, ...] = ("admin_l1_id", "admin_l2_id", "admin_l3_id", "admin_l4_id")
    filters: tuple[ValueFilter, ...] = field(
        default=(
            ValueFilter("eventType", "event_type"),
            ValueFilter("eventSubtype", "event_subtype"),
            ValueFilter("sourceType", "source_type", values=("device", "sensor", "external", "manual")),
            ValueFilter("deviceId", "device_id", "uuid"),
        )
    )


EVENTS: Final = EventFields()

# --- registry self-check ---------------------------------------------------------------------------------
# Everything in this module is written into SQL, so the shapes are checked once at import: a typo or an
# unexpected character here would be a defect in the service, not in a request.
_CODE = re.compile(r"^(ref|ops)\.[a-z][a-z0-9_]{1,62}$")
_COLUMN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_KEY = re.compile(r"^[a-z][A-Za-z0-9]{0,62}$")
# ``t.column`` or a single call around it, e.g. ``lower(t.valid_during)``.
_EXPRESSION = re.compile(r"^(?:[a-z_]{1,32}\()?t\.[a-z][a-z0-9_]{0,62}\)?$")
_VALUE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_FILTER_NAME = re.compile(r"^[a-z][A-Za-z0-9]{0,32}$")


def _check_filters(filters: tuple[ValueFilter, ...], where: str) -> None:
    for value_filter in filters:
        assert _FILTER_NAME.fullmatch(value_filter.name), f"{where}: filter name {value_filter.name!r}"
        assert _COLUMN.fullmatch(value_filter.column), f"{where}: filter column {value_filter.column!r}"
        for value in value_filter.values:
            assert _VALUE.fullmatch(value), f"{where}: filter value {value!r}"


def check_registry(layers: tuple[SpatialLayer, ...] = LAYERS, events: EventFields = EVENTS) -> None:
    """Assert the shapes of everything that is written into SQL (called at import; tests reuse it)."""
    for layer in layers:
        assert _CODE.fullmatch(layer.code), f"layer code {layer.code!r}"
        columns = (
            layer.geometry_column,
            layer.metric_column,
            layer.id_column,
            *(c for c in (layer.name_column, layer.period_column, layer.definition_column) if c),
            *(c for c in (layer.radius_column, layer.area_kind) if c),
        )
        for column in columns:
            assert _COLUMN.fullmatch(column), f"{layer.code}: column {column!r}"
        keys = [prop.key for prop in layer.properties]
        assert len(keys) == len(set(keys)), f"{layer.code}: duplicate property keys"
        for prop in layer.properties:
            assert _KEY.fullmatch(prop.key), f"{layer.code}: property key {prop.key!r}"
            assert _EXPRESSION.fullmatch(prop.expression), f"{layer.code}: expression {prop.expression!r}"
        names = [f.name for f in layer.all_filters]
        assert len(names) == len(set(names)), f"{layer.code}: duplicate filter names"
        _check_filters(layer.all_filters, layer.code)
        assert (layer.containment == "area_part") == (layer.area_kind is not None), layer.code
        assert (layer.containment == "geofence") == (layer.definition_column is not None), layer.code
        assert layer.containment == "geometry" or layer.areal, layer.code
    for prop in events.properties:
        assert _KEY.fullmatch(prop.key), f"events: property key {prop.key!r}"
        assert _EXPRESSION.fullmatch(prop.expression), f"events: expression {prop.expression!r}"
    _check_filters(events.filters, "events")
    for column in events.admin_columns:
        assert _COLUMN.fullmatch(column), f"events: column {column!r}"


check_registry()
