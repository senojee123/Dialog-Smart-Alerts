from __future__ import annotations

import math
from itertools import pairwise

import pytest

from app.core.config import DEFAULT_SERVICE_AREA_BBOX
from app.core.errors import CoordinateError
from app.spatial.service_area import ServiceArea
from app.spatial.validation import validate_position

AREA = ServiceArea.from_bbox(DEFAULT_SERVICE_AREA_BBOX)


@pytest.mark.parametrize(
    ("lon", "lat"),
    [
        (80.77171308333334, 7.000471527777778),  # EPSG:5235 natural origin
        (79.44, 5.66),  # service-area corner (inclusive)
        (82.15, 10.08),  # opposite corner (inclusive)
    ],
)
def test_positions_inside_the_service_area_are_accepted(lon: float, lat: float) -> None:
    validate_position(lon, lat, AREA)


def test_swapped_axes_are_reported_as_such() -> None:
    with pytest.raises(CoordinateError) as info:
        validate_position(7.0, 80.7, AREA)
    assert info.value.extensions["likelySwapped"] is True
    assert "[longitude, latitude]" in info.value.detail


def test_position_outside_the_service_area_is_rejected() -> None:
    with pytest.raises(CoordinateError) as info:
        validate_position(77.59, 12.97, AREA)  # Bengaluru
    assert "likelySwapped" not in info.value.extensions
    assert info.value.extensions["serviceAreaBbox"] == list(DEFAULT_SERVICE_AREA_BBOX)


@pytest.mark.parametrize(("lon", "lat"), [(181.0, 7.0), (80.0, -91.0)])
def test_positions_outside_wgs84_bounds_are_rejected(lon: float, lat: float) -> None:
    with pytest.raises(CoordinateError, match="WGS84 bounds"):
        validate_position(lon, lat, AREA)


@pytest.mark.parametrize(("lon", "lat"), [(math.nan, 7.0), (80.0, math.inf), (-math.inf, 7.0)])
def test_non_finite_positions_are_rejected(lon: float, lat: float) -> None:
    with pytest.raises(CoordinateError, match="finite"):
        validate_position(lon, lat, AREA)


def test_service_area_geojson_ring_is_closed_and_counter_clockwise() -> None:
    geometry = AREA.to_geojson_geometry()
    ring = geometry["coordinates"][0]
    assert geometry["type"] == "Polygon"
    assert ring[0] == ring[-1]
    assert len(ring) == 5
    # Shoelace formula: positive signed area means counter-clockwise (RFC 7946 exterior rings).
    signed_area = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairwise(ring)) / 2
    assert signed_area > 0
    assert AREA.bbox == DEFAULT_SERVICE_AREA_BBOX
