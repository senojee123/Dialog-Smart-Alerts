"""The contracts the spatial query API rests on, checked without a database.

* the layer registry names real tables and real columns, and only safe identifiers
* the statements the repository builds contain no client value - every one is a bound parameter
* requests are validated where they arrive: CRS, bounding boxes, filters, geofence definitions
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import shapely
from pydantic import ValidationError

from app.core.errors import UnsupportedFilterError
from app.db.base import Base
from app.repositories.spatial_query import (
    ContainmentQuery,
    DistanceQuery,
    EventQuery,
    FeatureQuery,
    containment_statement,
    distance_statement,
    escape_like,
    events_statement,
    features_statement,
)
from app.repositories.spatial_query import UnsupportedFilterError as RepositoryFilterError
from app.schemas.operational import GeofenceDefinition, OperationalListQuery, Ownership, Period
from app.schemas.spatial_query import (
    ContainsQuery,
    EventListQuery,
    FeatureListQuery,
    LayerFilters,
    NearestQuery,
    WithinDistanceQuery,
)
from app.services.spatial_query import LayerNotFoundError, check_filters, resolve_layer
from app.spatial.layers import (
    EVENTS,
    LAYERS,
    LAYERS_BY_CODE,
    Property,
    SpatialLayer,
    ValueFilter,
    check_registry,
)
from app.spatial.service_area import ServiceArea
from app.spatial.validation import InvalidBboxError, parse_bbox

AREA = ServiceArea.from_bbox((79.44, 5.66, 82.15, 10.08))
POINT = {"type": "Point", "coordinates": [80.75, 8.03]}
WKB = shapely.to_wkb(shapely.Point(80.75, 8.03), output_dimension=2)
_COLUMN_OF = re.compile(r"t\.([a-z_0-9]+)")


def _table(code: str) -> Any:
    schema, name = code.split(".", 1)
    return Base.metadata.tables[f"{schema}.{name}"]


# --- the registry describes the real schema --------------------------------------------------------------


def test_the_registry_is_checked_at_import() -> None:
    check_registry()  # the module already ran this; calling it again documents that it is a contract


@pytest.mark.parametrize(
    "layer",
    [
        pytest.param(
            SpatialLayer(
                code="ref.settlement",
                scope="release",
                geometry_kinds=frozenset({"point"}),
                properties=(Property(key="name", expression="(SELECT 1)"),),
            ),
            id="expression that is not a column",
        ),
        pytest.param(
            SpatialLayer(
                code="ops.device; DROP TABLE x",
                scope="tenant",
                geometry_kinds=frozenset({"point"}),
                properties=(),
            ),
            id="table name that is not an identifier",
        ),
        pytest.param(
            SpatialLayer(
                code="ref.road",
                scope="release",
                geometry_kinds=frozenset({"line"}),
                properties=(),
                filters=(ValueFilter("type", "road_class OR true"),),
            ),
            id="filter column that is not an identifier",
        ),
    ],
)
def test_the_registry_check_rejects_anything_that_is_not_an_identifier(layer: SpatialLayer) -> None:
    with pytest.raises(AssertionError):
        check_registry((layer,))


@pytest.mark.parametrize("layer", LAYERS, ids=[layer.code for layer in LAYERS])
def test_every_layer_names_a_table_of_this_schema(layer: SpatialLayer) -> None:
    table = _table(layer.code)
    columns = set(table.columns.keys())

    expected = {layer.geometry_column, layer.metric_column, layer.id_column}
    expected |= {c for c in (layer.name_column, layer.period_column, layer.definition_column) if c}
    expected |= {c for c in (layer.radius_column,) if c}
    assert expected <= columns, f"{layer.code}: {expected - columns}"
    for value_filter in layer.all_filters:
        assert value_filter.column in columns, f"{layer.code}: filter on {value_filter.column}"
    for prop in layer.properties:
        column = _COLUMN_OF.search(prop.expression)
        assert column is not None, prop.expression
        assert column.group(1) in columns, f"{layer.code}: {prop.expression}"


def test_the_event_fields_name_columns_of_the_event_tables() -> None:
    location = set(_table(EVENTS.table).columns.keys())
    context = set(_table(EVENTS.context_table).columns.keys())

    for prop in EVENTS.properties:
        column = _COLUMN_OF.search(prop.expression)
        assert column is not None, prop.expression
        assert column.group(1) in location, prop.expression
    for value_filter in EVENTS.filters:
        assert value_filter.column in location
    for admin_column in EVENTS.admin_columns:
        assert admin_column in context
        assert f"{admin_column.removesuffix('_id')}_code" in context


def test_operational_layers_expose_the_lifecycle_status_they_can_be_filtered_by() -> None:
    """A map colours a device, site or geofence by its status, so it has to be a property as well as a
    filter: a filter narrows an answer, a property is what the answer carries."""
    for code in ("ops.site", "ops.device", "ops.geofence"):
        layer = LAYERS_BY_CODE[code]
        assert layer.status is not None, code
        assert "status" in layer.property_keys, code


def test_only_layers_with_areas_answer_containment() -> None:
    for layer in LAYERS:
        assert ("contains" in layer.capabilities) == layer.areal


def test_an_unknown_layer_is_refused_before_any_sql_is_built() -> None:
    with pytest.raises(LayerNotFoundError) as info:
        resolve_layer("ref.settlement; DROP TABLE ref.settlement")

    assert info.value.extensions["queryableLayers"] == sorted(LAYERS_BY_CODE)


# --- statements carry values as parameters ---------------------------------------------------------------


def test_a_feature_statement_binds_every_value() -> None:
    layer = LAYERS_BY_CODE["ref.settlement"]
    release = uuid.uuid4()
    after = uuid.uuid4()

    statement, params = features_statement(
        FeatureQuery(
            layer=layer,
            limit=51,
            release_id=release,
            bbox=(80.7, 8.0, 80.8, 8.1),
            filters={"type": "town"},
            name_contains="fixture",
            after_id=after,
        )
    )

    assert "ref.settlement AS t" in statement
    assert "t.settlement_type = CAST(:f_type AS text)" in statement
    assert "OPERATOR(public.&&)" in statement  # the bounding box drives the index
    assert "ORDER BY t.id" in statement
    for value in ("town", "fixture", str(release), str(after), "80.7", "51"):
        assert value not in statement, f"{value!r} was written into the statement"
    assert params["f_type"] == "town"
    assert params["name_pattern"] == "%fixture%"
    assert params["release_id"] == release
    assert params["after_id"] == after
    assert params["limit"] == 51
    assert params["min_lon"] == 80.7


def test_a_filter_the_layer_does_not_have_never_reaches_sql() -> None:
    layer = LAYERS_BY_CODE["ref.road"]

    with pytest.raises(RepositoryFilterError):
        features_statement(FeatureQuery(layer=layer, limit=10, release_id=uuid.uuid4(), filters={"level": 2}))
    with pytest.raises(RepositoryFilterError):
        events_statement(EventQuery(time_from=_now(), time_to=_now(), limit=10, filters={"nope": "x"}))


def _now() -> datetime:
    return datetime(2026, 9, 10, tzinfo=UTC)


def test_a_distance_statement_is_bounded_and_ordered_by_distance() -> None:
    layer = LAYERS_BY_CODE["ref.settlement"]

    statement, params = distance_statement(
        DistanceQuery(
            layer=layer,
            limit=11,
            geometry_wkb=WKB,
            distance_m=500.0,
            release_id=uuid.uuid4(),
            after_distance_m=123.45,
            after_id=uuid.uuid4(),
        )
    )

    within = "public.ST_DWithin(t.geom_metric, e.geom_metric, CAST(:distance_m AS double precision))"
    assert within in statement
    assert "public.ST_Expand(e.geom_metric" in statement
    assert "OPERATOR(public.<->)" in statement  # nearest-first uses the KNN operator
    assert "500" not in statement
    assert "123.45" not in statement
    assert params["distance_m"] == 500.0
    assert params["after_distance_m"] == 123.45
    assert params["wkb"] == WKB


def test_geofence_distances_measure_to_the_definition_and_radius() -> None:
    statement, _ = distance_statement(
        DistanceQuery(
            layer=LAYERS_BY_CODE["ops.geofence"], limit=5, geometry_wkb=WKB, distance_m=500.0, at=_now()
        )
    )

    assert "t.definition_geom_metric" in statement
    assert "greatest(" in statement  # 0 inside the circle, distance to its edge outside
    assert "OPERATOR(public.<->)" not in statement  # KNN cannot order an expression like this
    assert "t.effective_during @> CAST(:at AS timestamptz)" in statement


def test_containment_uses_the_subdivided_parts_for_reference_areas() -> None:
    statement, params = containment_statement(
        ContainmentQuery(
            layer=LAYERS_BY_CODE["ref.protected_area"],
            limit=10,
            geometry_wkb=WKB,
            release_id=uuid.uuid4(),
        )
    )

    assert "ref.area_part AS p" in statement
    assert "p.area_kind = CAST(:area_kind AS text)" in statement
    assert params["area_kind"] == "protected_area"
    assert "public.ST_Covers(t.geom, e.geom)" in statement
    # In covers mode the containment is the condition, so the relation is known without testing twice.
    assert statement.count("public.ST_Covers(t.geom, e.geom)") == 1
    assert "'within'" in statement
    assert "'intersects'" not in statement


def test_containment_of_a_circle_geofence_tests_the_exact_shape() -> None:
    statement, _ = containment_statement(
        ContainmentQuery(layer=LAYERS_BY_CODE["ops.geofence"], limit=10, geometry_wkb=WKB, at=_now())
    )

    assert "t.geom_metric OPERATOR(public.&&) e.geom_metric" in statement
    # A point: the inclusive distance to the definition. A line or area: the farthest point from a
    # circle's centre, or the finely drawn buffer of a corridor's centre line.
    assert "public.ST_DWithin(t.definition_geom_metric, e.geom_metric" in statement
    assert "public.ST_MaxDistance(t.definition_geom_metric, e.geom_metric)" in statement
    assert "public.ST_Buffer(t.definition_geom_metric" in statement
    assert "quad_segs=512" in statement


def test_intersection_mode_reports_the_relation_it_found() -> None:
    covers, _ = containment_statement(
        ContainmentQuery(
            layer=LAYERS_BY_CODE["ref.risk_zone"],
            limit=1,
            geometry_wkb=WKB,
            at=_now(),
            covers=True,
            release_id=uuid.uuid4(),
        )
    )
    intersects, _ = containment_statement(
        ContainmentQuery(
            layer=LAYERS_BY_CODE["ref.risk_zone"],
            limit=1,
            geometry_wkb=WKB,
            at=_now(),
            covers=False,
            release_id=uuid.uuid4(),
        )
    )

    assert "public.ST_Covers(t.geom, e.geom)" in covers
    assert "public.ST_Intersects(t.geom, e.geom)" in intersects
    # Only an intersecting query has to decide between within and intersects.
    assert "'intersects'" in intersects
    assert "public.ST_Covers(t.geom, e.geom)" in intersects


def test_an_event_statement_bounds_the_window_and_pages_newest_first() -> None:
    geofence = uuid.uuid4()

    statement, params = events_statement(
        EventQuery(
            time_from=_now(),
            time_to=_now(),
            limit=26,
            bbox=(80.7, 8.0, 80.8, 8.1),
            filters={"eventType": "wildlife.elephant_detected"},
            geofence_id=geofence,
            admin_area_code="SYN-D1",
            after_observed_at=_now(),
            after_event_id="evt-1",
        )
    )

    assert "t.observed_at >= CAST(:time_from AS timestamptz)" in statement
    assert "ORDER BY t.observed_at DESC" in statement
    assert 't.event_id COLLATE "C" DESC' in statement
    assert "geo.event_geofence_hit AS h" in statement
    assert "c.admin_l4_code = CAST(:admin_area_code AS text)" in statement
    assert "SYN-D1" not in statement
    assert "evt-1" not in statement
    assert params["geofence_id"] == geofence
    assert params["f_eventType"] == "wildlife.elephant_detected"


def test_a_name_search_cannot_become_a_wildcard() -> None:
    assert escape_like("100%_a\\b") == "100\\%\\_a\\\\b"

    _, params = features_statement(
        FeatureQuery(
            layer=LAYERS_BY_CODE["ref.settlement"],
            limit=1,
            release_id=uuid.uuid4(),
            name_contains="100%",
        )
    )
    assert params["name_pattern"] == "%100\\%%"


def test_geometry_is_left_out_when_it_is_not_wanted() -> None:
    layer = LAYERS_BY_CODE["ref.admin_area"]
    with_geometry, _ = features_statement(
        FeatureQuery(layer=layer, limit=1, release_id=uuid.uuid4(), include_geometry=True)
    )
    without, _ = features_statement(
        FeatureQuery(layer=layer, limit=1, release_id=uuid.uuid4(), include_geometry=False)
    )

    assert "public.ST_AsGeoJSON(t.geom, 7)::jsonb AS geometry" in with_geometry
    assert "NULL::jsonb AS geometry" in without


# --- request validation ----------------------------------------------------------------------------------


@pytest.mark.parametrize("crs", ["EPSG:4326", "epsg:4326", "CRS84", "urn:ogc:def:crs:OGC::CRS84", None])
def test_wgs84_is_accepted_as_the_coordinate_reference_system(crs: str | None) -> None:
    query = WithinDistanceQuery.model_validate(
        {"target": "ref.settlement", "geometry": POINT, "distanceM": 100, "crs": crs}
    )

    assert query.crs == crs


@pytest.mark.parametrize("crs", ["EPSG:5235", "EPSG:3857", "urn:ogc:def:crs:EPSG::32644", "SLD99"])
def test_any_other_coordinate_reference_system_is_refused(crs: str) -> None:
    with pytest.raises(ValidationError, match="WGS84"):
        NearestQuery.model_validate({"target": "ref.settlement", "geometry": POINT, "crs": crs})


def test_a_geojson_crs_member_is_not_accepted() -> None:
    with pytest.raises(ValidationError):
        ContainsQuery.model_validate(
            {
                "target": "ref.protected_area",
                "geometry": {**POINT, "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}},
            }
        )


@pytest.mark.parametrize(
    ("bbox", "match"),
    [
        ("80.7,8.0,80.8", "four numbers"),
        ("a,b,c,d", "four numbers"),
        ("80.8,8.0,80.7,8.1", "minLon < maxLon"),
        ("80.7,8.1,80.8,8.0", "minLon < maxLon"),
        ("-181,8.0,80.8,8.1", "minLon < maxLon"),
        ("70.0,1.0,75.0,3.0", "does not overlap"),
    ],
)
def test_a_bounding_box_is_validated(bbox: str, match: str) -> None:
    with pytest.raises(InvalidBboxError, match=match):
        parse_bbox(bbox, AREA)


def test_a_bounding_box_may_be_wider_than_the_service_area() -> None:
    assert parse_bbox("70.0, 0.0, 90.0, 15.0", AREA) == (70.0, 0.0, 90.0, 15.0)


def test_filters_are_reported_with_what_the_layer_supports() -> None:
    layer = LAYERS_BY_CODE["ref.road"]

    with pytest.raises(UnsupportedFilterError) as info:
        check_filters(layer, {"level": 2})

    assert info.value.extensions["supportedFilters"] == ["type", "refCode"]

    with pytest.raises(UnsupportedFilterError) as bad_value:
        check_filters(layer, {"type": "motorway"})
    assert "A" in bad_value.value.extensions["allowedValues"]


def test_only_the_filters_that_were_given_are_applied() -> None:
    params = FeatureListQuery.model_validate({"type": "town", "limit": 5})

    assert params.as_mapping() == {"type": "town"}


def test_event_filters_use_the_names_of_the_event_registry() -> None:
    params = EventListQuery.model_validate({"eventType": "wildlife.elephant_detected", "limit": 5})

    assert params.as_mapping() == {"eventType": "wildlife.elephant_detected"}
    assert {name for name in params.as_mapping()} <= {f.name for f in EVENTS.filters}


def test_a_filter_key_is_a_registry_filter_name() -> None:
    every_filter = {f.name for layer in LAYERS for f in layer.all_filters}

    assert set(LayerFilters.model_validate({}).model_dump(by_alias=True)) <= every_filter | {"status", "type"}


# --- geofence definitions --------------------------------------------------------------------------------


def test_a_polygon_geofence_has_no_radius() -> None:
    ring = [[80.7, 8.0], [80.8, 8.0], [80.8, 8.1], [80.7, 8.1], [80.7, 8.0]]
    box = {"type": "Polygon", "coordinates": [ring]}

    definition = GeofenceDefinition.model_validate({"kind": "polygon", "geometry": box})
    assert definition.radius_m is None

    with pytest.raises(ValidationError, match="no radiusM"):
        GeofenceDefinition.model_validate({"kind": "polygon", "geometry": box, "radiusM": 100})
    with pytest.raises(ValidationError, match="Polygon or MultiPolygon"):
        GeofenceDefinition.model_validate({"kind": "polygon", "geometry": POINT})


def test_a_circle_geofence_is_a_point_and_a_radius() -> None:
    definition = GeofenceDefinition.model_validate({"kind": "circle", "geometry": POINT, "radiusM": 500})
    assert definition.radius_m == 500

    with pytest.raises(ValidationError, match="needs radiusM"):
        GeofenceDefinition.model_validate({"kind": "circle", "geometry": POINT})
    with pytest.raises(ValidationError, match="Point centre"):
        GeofenceDefinition.model_validate(
            {
                "kind": "circle",
                "geometry": {"type": "LineString", "coordinates": [[80.7, 8.0], [80.8, 8.0]]},
                "radiusM": 500,
            }
        )
    with pytest.raises(ValidationError):
        GeofenceDefinition.model_validate({"kind": "circle", "geometry": POINT, "radiusM": 50_001})


def test_a_corridor_geofence_is_a_line_and_a_half_width() -> None:
    line = {"type": "LineString", "coordinates": [[80.70, 8.01], [80.80, 8.01]]}

    definition = GeofenceDefinition.model_validate({"kind": "corridor", "geometry": line, "radiusM": 50})
    assert definition.kind == "corridor"

    with pytest.raises(ValidationError, match="LineString or MultiLineString"):
        GeofenceDefinition.model_validate({"kind": "corridor", "geometry": POINT, "radiusM": 50})
    with pytest.raises(ValidationError, match="half-width"):
        GeofenceDefinition.model_validate({"kind": "corridor", "geometry": line, "radiusM": 5_001})


def test_sharing_with_named_tenants_requires_the_shared_policy() -> None:
    assert Ownership.model_validate(
        {"sharingPolicy": "shared", "sharedWithTenants": ["other-tenant"]}
    ).shared_with_tenants == ["other-tenant"]

    with pytest.raises(ValidationError, match="requires sharingPolicy"):
        Ownership.model_validate({"sharingPolicy": "private", "sharedWithTenants": ["other-tenant"]})
    with pytest.raises(ValidationError, match="not a tenant id"):
        Ownership.model_validate({"sharingPolicy": "shared", "sharedWithTenants": ["Not A Tenant"]})
    with pytest.raises(ValidationError, match="must not repeat"):
        Ownership.model_validate({"sharingPolicy": "shared", "sharedWithTenants": ["a-tenant", "a-tenant"]})


def test_a_period_ends_after_it_starts() -> None:
    with pytest.raises(ValidationError, match="after"):
        Period.model_validate({"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"})


def test_list_filters_have_bounds() -> None:
    with pytest.raises(ValidationError):
        OperationalListQuery.model_validate({"limit": 0})
    with pytest.raises(ValidationError):
        OperationalListQuery.model_validate({"limit": 1001})
    assert OperationalListQuery.model_validate({}).limit == 100
