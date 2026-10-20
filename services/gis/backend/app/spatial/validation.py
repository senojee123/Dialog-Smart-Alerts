"""Coordinate validation shared by every endpoint that accepts positions (plan Section 5.2).

Input is GeoJSON (RFC 7946): WGS84 with ``[longitude, latitude]`` axis order. Positions outside the
service area are rejected; when the swapped pair would be inside it, the error says so, because
``[lat, lon]`` input is the most common integration mistake.

Bounding boxes follow the GeoJSON order ``minLon,minLat,maxLon,maxLat``. A viewport may be wider than
the service area - a map view usually is - so a box only has to overlap it.
"""

from __future__ import annotations

import math
from typing import Final

from app.core.errors import CoordinateError, GisValidationError
from app.spatial.service_area import ServiceArea

BBOX_PARTS: Final = 4
Bbox = tuple[float, float, float, float]


class InvalidBboxError(GisValidationError):
    code = "invalid_bbox"
    title = "Bounding box is not acceptable"


def validate_position(lon: float, lat: float, area: ServiceArea) -> None:
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise CoordinateError("coordinates must be finite numbers", extensions={"position": [lon, lat]})
    if not (-180.0 <= lon <= 180.0) or not (-90.0 <= lat <= 90.0):
        raise CoordinateError(
            "coordinates are outside WGS84 bounds; GeoJSON positions are [longitude, latitude]",
            extensions={"position": [lon, lat]},
        )
    if area.contains(lon, lat):
        return
    if area.contains(lat, lon):
        raise CoordinateError(
            "position is outside the service area but would be inside it with the axes swapped; "
            "GeoJSON positions must be [longitude, latitude]",
            extensions={"position": [lon, lat], "likelySwapped": True},
        )
    raise CoordinateError(
        "position is outside the service area",
        extensions={"position": [lon, lat], "serviceAreaBbox": list(area.bbox)},
    )


def parse_bbox(value: str, area: ServiceArea) -> Bbox:
    """``minLon,minLat,maxLon,maxLat`` as four floats, checked against WGS84 and the service area."""
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != BBOX_PARTS:
        raise InvalidBboxError(
            "bbox must be four numbers: minLon,minLat,maxLon,maxLat", extensions={"bbox": value}
        )
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise InvalidBboxError(
            "bbox must be four numbers: minLon,minLat,maxLon,maxLat", extensions={"bbox": value}
        ) from exc
    if not all(math.isfinite(number) for number in numbers):
        raise InvalidBboxError("bbox numbers must be finite", extensions={"bbox": value})
    min_lon, min_lat, max_lon, max_lat = numbers
    if not (-180.0 <= min_lon < max_lon <= 180.0) or not (-90.0 <= min_lat < max_lat <= 90.0):
        raise InvalidBboxError(
            "bbox must satisfy -180 <= minLon < maxLon <= 180 and -90 <= minLat < maxLat <= 90; "
            "positions are [longitude, latitude]",
            extensions={"bbox": numbers},
        )
    area_min_lon, area_min_lat, area_max_lon, area_max_lat = area.bbox
    if min_lon > area_max_lon or max_lon < area_min_lon or min_lat > area_max_lat or max_lat < area_min_lat:
        raise InvalidBboxError(
            "bbox does not overlap the service area",
            extensions={"bbox": numbers, "serviceAreaBbox": list(area.bbox)},
        )
    return min_lon, min_lat, max_lon, max_lat
