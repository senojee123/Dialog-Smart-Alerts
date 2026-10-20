"""GeoJSON geometry intake (app/spatial/geometry.py): the application-side twin of the database checks."""

from __future__ import annotations

import math
from typing import Any

import pytest
import shapely
from pyproj import Geod
from shapely import Point, box

from app.core.config import DEFAULT_SERVICE_AREA_BBOX
from app.core.errors import CoordinateError, InvalidGeometryError
from app.schemas.geojson import GeoJsonGeometry
from app.spatial.crs import to_metric
from app.spatial.geometry import (
    POINT_TYPES,
    POLYGON_TYPES,
    GeometryKind,
    parse_geojson_geometry,
    repair_polygonal,
)
from app.spatial.service_area import ServiceArea

AREA = ServiceArea.from_bbox(DEFAULT_SERVICE_AREA_BBOX)
BOW_TIE = [[[80.7, 8.0], [80.8, 8.1], [80.8, 8.0], [80.7, 8.1], [80.7, 8.0]]]


def parse(obj: dict[str, Any], **kwargs: Any) -> Any:
    return parse_geojson_geometry(obj, area=AREA, **kwargs)


# --- Sri Lankan and foreign coordinates -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lon", "lat"),
    [
        (79.857751, 6.931966),  # Colombo
        (80.749, 8.037),  # Habarana
        (80.5895, 5.9235),  # Dondra Head
        (80.2346, 9.8167),  # Point Pedro
        (79.44, 5.66),  # service-area corner, inclusive
    ],
)
def test_sri_lankan_points_are_accepted(lon: float, lat: float) -> None:
    validated = parse({"type": "Point", "coordinates": [lon, lat]})
    assert validated.kind is GeometryKind.POINT
    assert validated.geometry_type == "POINT"
    assert shapely.from_wkb(validated.wkb()).equals(Point(lon, lat))


@pytest.mark.parametrize(
    ("lon", "lat"),
    [(80.27, 13.08), (73.51, 4.17), (77.59, 12.97), (0.0, 0.0), (79.4399, 7.0)],
)
def test_points_outside_sri_lanka_are_rejected(lon: float, lat: float) -> None:
    with pytest.raises(CoordinateError, match="outside the service area") as info:
        parse({"type": "Point", "coordinates": [lon, lat]})
    assert "likelySwapped" not in info.value.extensions
    assert info.value.extensions["serviceAreaBbox"] == list(DEFAULT_SERVICE_AREA_BBOX)


def test_swapped_point_is_reported() -> None:
    with pytest.raises(CoordinateError, match="axes swapped") as info:
        parse({"type": "Point", "coordinates": [6.931966, 79.857751]})
    assert info.value.extensions["likelySwapped"] is True
    assert info.value.extensions["path"] == "coordinates"


def test_swapped_polygon_is_reported_only_when_every_position_fits_swapped() -> None:
    swapped = [[[8.0, 80.7], [8.0, 80.8], [8.1, 80.8], [8.0, 80.7]]]
    with pytest.raises(CoordinateError) as info:
        parse({"type": "Polygon", "coordinates": swapped})
    assert info.value.extensions["likelySwapped"] is True
    partly = [[[80.7, 8.0], [80.8, 8.0], [90.0, 12.0], [80.7, 8.0]]]
    with pytest.raises(CoordinateError, match="1 of 4 positions") as info:
        parse({"type": "Polygon", "coordinates": partly})
    assert "likelySwapped" not in info.value.extensions
    assert info.value.extensions["path"] == "coordinates[0][2]"


def test_latitude_beyond_90_is_reported_as_swapped() -> None:
    with pytest.raises(CoordinateError, match="WGS84 bounds") as info:
        parse({"type": "Point", "coordinates": [7.0, 180.0]})
    assert info.value.extensions["likelySwapped"] is True


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_coordinates_are_rejected(value: float) -> None:
    with pytest.raises(CoordinateError, match="finite"):
        parse({"type": "Point", "coordinates": [value, 8.0]})


# --- structure --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("obj", "message"),
    [
        ({"type": "GeometryCollection", "geometries": []}, "GeometryCollection is not supported"),
        ({"type": "Circle", "coordinates": [80.7, 8.0]}, "unsupported geometry type"),
        ({"type": "Point"}, "no coordinates"),
        ({"type": "Point", "coordinates": [80.7]}, "must be a position"),
        ({"type": "Point", "coordinates": [80.7, 8.0, 1.0, 2.0]}, "must be a position"),
        ({"type": "Point", "coordinates": ["80.7", 8.0]}, "numbers only"),
        ({"type": "Point", "coordinates": [True, 8.0]}, "numbers only"),
        ({"type": "LineString", "coordinates": [[80.7, 8.0]]}, "at least two positions"),
        ({"type": "LineString", "coordinates": [80.7, 8.0]}, "must be a position"),
        ({"type": "MultiPoint", "coordinates": []}, "empty"),
        ({"type": "Polygon", "coordinates": [[[80.7, 8.0], [80.8, 8.0], [80.7, 8.0]]]}, "at least four"),
        (
            {"type": "Polygon", "coordinates": [[[80.7, 8.0], [80.8, 8.0], [80.8, 8.1], [80.7, 8.1]]]},
            "must be closed",
        ),
        ({"type": "Polygon", "coordinates": []}, "empty"),
        ({"type": "MultiPolygon", "coordinates": [[]]}, "empty"),
    ],
)
def test_malformed_geometries_are_rejected(obj: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidGeometryError, match=message):
        parse(obj)


def test_types_can_be_restricted() -> None:
    with pytest.raises(InvalidGeometryError, match="not accepted here") as info:
        parse({"type": "LineString", "coordinates": [[80.7, 8.0], [80.8, 8.0]]}, allowed_types=POINT_TYPES)
    assert info.value.extensions["allowedTypes"] == ["Point"]


def test_vertex_limit() -> None:
    ring = [[80.7 + i * 1e-5, 8.0] for i in range(50)] + [[80.7, 8.1], [80.7, 8.0]]
    with pytest.raises(InvalidGeometryError, match="limit is 10"):
        parse({"type": "Polygon", "coordinates": [ring]}, max_vertices=10)


def test_altitude_is_dropped() -> None:
    validated = parse({"type": "LineString", "coordinates": [[80.7, 8.0, 120.5], [80.8, 8.1, 130.0]]})
    assert not validated.geometry.has_z
    assert validated.kind is GeometryKind.LINE


# --- validity ---------------------------------------------------------------------------------------------


def test_invalid_polygon_is_rejected_with_reason_by_default() -> None:
    with pytest.raises(InvalidGeometryError, match="Self-intersection") as info:
        parse({"type": "Polygon", "coordinates": BOW_TIE})
    assert info.value.extensions["reason"].startswith("Self-intersection[80.75 8.05")


def test_invalid_polygon_can_be_repaired() -> None:
    validated = parse({"type": "Polygon", "coordinates": BOW_TIE}, invalid_polygons="repair")
    assert validated.repaired
    assert validated.is_valid
    assert validated.geometry.geom_type == "MultiPolygon"
    assert len(validated.geometry.geoms) == 2
    assert validated.kind is GeometryKind.AREA
    assert validated.invalid_reason is not None


def test_invalid_polygon_can_be_deferred_to_the_database() -> None:
    validated = parse({"type": "Polygon", "coordinates": BOW_TIE}, invalid_polygons="defer")
    assert not validated.is_valid
    assert not validated.repaired
    assert not validated.geometry.is_valid


def test_collapsed_polygon_cannot_be_repaired() -> None:
    collapsed = [[[80.7, 8.0], [80.8, 8.1], [80.7, 8.0], [80.7, 8.0]]]
    with pytest.raises(InvalidGeometryError, match="cannot be repaired"):
        parse({"type": "Polygon", "coordinates": collapsed}, invalid_polygons="repair")


def test_repair_keeps_only_polygonal_parts() -> None:
    spike = "POLYGON((80 8, 80.1 8, 80.1 8.1, 80.05 8.1, 80.05 8.2, 80.05 8.1, 80 8.1, 80 8))"
    assert not shapely.is_valid(shapely.from_wkt(spike))
    repaired = repair_polygonal(shapely.from_wkt(spike))
    assert repaired.is_valid
    assert {part.geom_type for part in shapely.get_parts(repaired)} == {"Polygon"}


def test_polygon_with_hole_is_valid() -> None:
    validated = parse(
        {
            "type": "Polygon",
            "coordinates": [
                [[80.76, 8.04], [80.79, 8.04], [80.79, 8.07], [80.76, 8.07], [80.76, 8.04]],
                [[80.77, 8.05], [80.77, 8.06], [80.78, 8.06], [80.78, 8.05], [80.77, 8.05]],
            ],
        },
        allowed_types=POLYGON_TYPES,
    )
    polygon = validated.geometry
    # Inside, in the hole, on the boundary (boundary inclusive, as in the database).
    assert polygon.covers(Point(80.765, 8.045))
    assert not polygon.covers(Point(80.775, 8.055))
    assert polygon.covers(Point(80.76, 8.05))
    assert polygon.covers(Point(80.77, 8.055))  # on the hole's edge
    assert not polygon.covers(Point(80.80, 8.05))


# --- metric thresholds ------------------------------------------------------------------------------------


def test_distance_threshold_is_inclusive_in_the_metric_crs() -> None:
    a = to_metric(Point(80.745, 8.010))
    b = to_metric(Point(80.755, 8.015))
    distance = a.distance(b)
    assert shapely.dwithin(a, b, distance)
    assert not shapely.dwithin(a, b, math.nextafter(distance, 0))
    assert 1_200 < distance < 1_300


def test_metric_area_matches_the_ellipsoidal_area() -> None:
    square = box(80.74, 8.02, 80.76, 8.04)
    geodesic_area = abs(Geod(ellps="WGS84").geometry_area_perimeter(square)[0])
    assert to_metric(square).area == pytest.approx(geodesic_area, rel=5e-4)


def test_output_geometry_is_rounded_and_keeps_vertex_order() -> None:
    source = box(80.123456789, 8.1, 80.2, 8.2, ccw=False)
    geometry = GeoJsonGeometry.from_shapely(source)
    ring = geometry.coordinates[0]
    assert geometry.type == "Polygon"
    assert {x for x, _ in ring} == {80.1234568, 80.2}
    assert [(round(x, 7), y) for x, y in source.exterior.coords] == [tuple(position) for position in ring]
