"""Spatial regression tests for the coordinate system conventions (ADR-02).

The SLD99 / Sri Lanka Grid 1999 parameters are those published in the EPSG registry for EPSG:5235:
natural origin latitude 7 deg 00' 01.6975" N, longitude 80 deg 46' 18.1671" E, scale factor
0.9999238418, false easting and northing 500 000 m.
"""

from __future__ import annotations

import math
import threading

import pytest
from pyproj import Geod, Transformer
from shapely import LineString, Point, Polygon

from app.spatial import crs

ORIGIN_LAT = 7 + 0 / 60 + 1.6975 / 3600
ORIGIN_LON = 80 + 46 / 60 + 18.1671 / 3600
WGS84_GEOD = Geod(ellps="WGS84")


def test_grid_natural_origin_maps_to_false_easting_and_northing() -> None:
    # Same datum (SLD99 geographic -> SLD99 grid): a pure projection, so the result is exact.
    transformer = Transformer.from_crs(crs.SLD99_GEOGRAPHIC, crs.SLD99_GRID, always_xy=True)
    easting, northing = transformer.transform(ORIGIN_LON, ORIGIN_LAT)
    assert easting == pytest.approx(500_000.0, abs=0.005)
    assert northing == pytest.approx(500_000.0, abs=0.005)


def test_wgs84_to_grid_includes_the_sld99_datum_shift() -> None:
    # The same numbers read as WGS84 land about 225 m from the grid origin: SLD99 is a different datum.
    easting, northing = crs.wgs84_to_metric_xy(ORIGIN_LON, ORIGIN_LAT)
    shift = math.hypot(easting - 500_000.0, northing - 500_000.0)
    assert 150.0 < shift < 300.0


@pytest.mark.parametrize(
    ("lon", "lat"),
    [(79.64, 5.86), (81.95, 5.86), (81.95, 9.88), (79.64, 9.88), (ORIGIN_LON, ORIGIN_LAT)],
)
def test_round_trip_error_is_below_5_mm(lon: float, lat: float) -> None:
    """PROJ inverts the SLD99 Helmert datum shift approximately; the round trip drifts by ~2 mm.

    That is far below any accuracy this service promises, but a larger drift would indicate a
    different (or missing) datum transformation, so it is pinned here.
    """
    back = crs.to_wgs84(crs.to_metric(Point(lon, lat)))
    _, _, drift_m = WGS84_GEOD.inv(lon, lat, back.x, back.y)
    assert drift_m < 0.005


@pytest.mark.parametrize(
    ("distance_m", "azimuth"), [(500.0, 0.0), (500.0, 90.0), (5_000.0, 45.0), (20_000.0, 135.0)]
)
@pytest.mark.parametrize(("lon", "lat"), [(ORIGIN_LON, ORIGIN_LAT), (79.9, 6.9), (81.2, 8.3)])
def test_grid_distances_match_geodesic_distances(
    lon: float, lat: float, distance_m: float, azimuth: float
) -> None:
    """Planar SLD99 distance must agree with the WGS84 geodesic within the projection's scale error.

    Transverse Mercator scale error across Sri Lanka stays below 250 ppm, so a 500 m rule threshold is
    reproduced to better than 0.125 m.
    """
    end_lon, end_lat, _ = WGS84_GEOD.fwd(lon, lat, azimuth, distance_m)
    x1, y1 = crs.wgs84_to_metric_xy(lon, lat)
    x2, y2 = crs.wgs84_to_metric_xy(end_lon, end_lat)
    planar = math.hypot(x2 - x1, y2 - y1)
    assert abs(planar - distance_m) <= distance_m * 250e-6


def test_geometry_transforms_preserve_type_and_topology() -> None:
    polygon = Polygon([(80.0, 7.0), (80.01, 7.0), (80.01, 7.01), (80.0, 7.01), (80.0, 7.0)])
    line = LineString([(80.0, 7.0), (80.01, 7.01)])
    metric_polygon = crs.to_metric(polygon)
    metric_line = crs.to_metric(line)
    assert metric_polygon.geom_type == "Polygon"
    assert metric_polygon.is_valid
    assert metric_line.geom_type == "LineString"
    # ~1.1 km x ~1.1 km at this latitude
    assert 1.1e6 < metric_polygon.area < 1.3e6


def test_transformers_are_cached_per_thread() -> None:
    first = crs.get_transformer(crs.WGS84, crs.SLD99_GRID)
    assert crs.get_transformer(crs.WGS84, crs.SLD99_GRID) is first
    other: list[Transformer] = []
    thread = threading.Thread(target=lambda: other.append(crs.get_transformer(crs.WGS84, crs.SLD99_GRID)))
    thread.start()
    thread.join()
    assert len(other) == 1
    assert other[0] is not first


def test_required_srids() -> None:
    assert frozenset({4326, 5235, 3857}) == crs.REQUIRED_SRIDS
    assert crs.proj_version()
