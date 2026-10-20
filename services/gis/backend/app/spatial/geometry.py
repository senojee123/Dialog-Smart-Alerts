"""GeoJSON geometry intake (RFC 7946) for everything the service stores.

``parse_geojson_geometry`` turns a GeoJSON geometry object into a validated Shapely geometry in
EPSG:4326 or raises a problem-details error that tells the client what to fix:

* only the geometry types the caller allows (``GeometryCollection`` is never accepted)
* positions are ``[longitude, latitude]`` or ``[longitude, latitude, altitude]``; altitude is dropped
* every position is finite, inside WGS84 bounds and inside the service area; when the geometry would
  be inside with the axes swapped, the error says so (``likelySwapped``)
* linear rings are closed and have at least four positions
* the geometry is valid (OGC simple features). Invalid polygons are rejected with the reason and
  location (API input), repaired, or passed on for the database to repair and log (reference data
  loading, see ``meta.normalise_reference_geometry``)

The database repeats the essential checks (``ST_IsValid``, service-area envelope) as constraints, so
nothing that bypasses this module can store an invalid or misplaced geometry either.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Literal

import shapely
from shapely import Geometry
from shapely.errors import GEOSException
from shapely.geometry import shape

from app.core.errors import CoordinateError, InvalidGeometryError
from app.spatial.crs import CANONICAL_SRID
from app.spatial.service_area import ServiceArea

GEOJSON_TYPES: Final = frozenset(
    {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}
)
POINT_TYPES: Final = frozenset({"Point"})
POLYGON_TYPES: Final = frozenset({"Polygon", "MultiPolygon"})
LINE_TYPES: Final = frozenset({"LineString", "MultiLineString"})
DEFAULT_MAX_VERTICES: Final = 20_000

# Nesting depth of "coordinates" per GeoJSON type.
_DEPTH: Final = {
    "Point": 0,
    "MultiPoint": 1,
    "LineString": 1,
    "MultiLineString": 2,
    "Polygon": 2,
    "MultiPolygon": 3,
}


class GeometryKind(StrEnum):
    POINT = "point"
    LINE = "line"
    AREA = "area"


InvalidPolygonPolicy = Literal["reject", "repair", "defer"]


@dataclass(frozen=True, slots=True)
class ValidatedGeometry:
    """A two-dimensional EPSG:4326 geometry inside the service area.

    ``geometry`` is valid unless ``invalid_reason`` is set, which happens only with the ``defer``
    policy (the database repairs the polygon on insert and logs the repair).
    """

    geometry: Geometry
    repaired: bool = False
    invalid_reason: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.invalid_reason is None or self.repaired

    @property
    def kind(self) -> GeometryKind:
        dimension = shapely.get_dimensions(self.geometry)
        return (GeometryKind.POINT, GeometryKind.LINE, GeometryKind.AREA)[int(dimension)]

    @property
    def geometry_type(self) -> str:
        """PostGIS-style upper-case type name, e.g. ``MULTIPOLYGON``."""
        return str(self.geometry.geom_type).upper()

    def wkb(self) -> bytes:
        """ISO WKB, 2D, for ``ST_GeomFromWKB(:wkb, 4326)``."""
        return bytes(shapely.to_wkb(self.geometry, output_dimension=2, include_srid=False))

    @property
    def srid(self) -> int:
        return CANONICAL_SRID


def _invalid(detail: str, **extensions: Any) -> InvalidGeometryError:
    return InvalidGeometryError(detail, extensions=extensions)


def _positions(coordinates: Any, depth: int, path: str) -> Iterator[tuple[str, Sequence[Any]]]:
    """Yield every position with its JSON path, checking the nesting structure on the way."""
    if depth == 0:
        yield path, coordinates
        return
    if not isinstance(coordinates, list | tuple):
        raise _invalid(f"{path} must be an array", path=path)
    for index, item in enumerate(coordinates):
        yield from _positions(item, depth - 1, f"{path}[{index}]")


def _position(path: str, value: Any) -> tuple[float, float]:
    if not isinstance(value, list | tuple) or len(value) not in (2, 3):
        raise _invalid(f"{path} must be a position [longitude, latitude] (altitude optional)", path=path)
    if not all(isinstance(number, int | float) and not isinstance(number, bool) for number in value):
        raise _invalid(f"{path} must contain numbers only", path=path)
    lon, lat = float(value[0]), float(value[1])
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise CoordinateError("coordinates must be finite numbers", extensions={"path": path})
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        swapped_ok = -180.0 <= lat <= 180.0 and -90.0 <= lon <= 90.0
        extensions: dict[str, Any] = {"path": path, "position": [lon, lat]}
        if swapped_ok:
            extensions["likelySwapped"] = True
        raise CoordinateError(
            "coordinates are outside WGS84 bounds; GeoJSON positions are [longitude, latitude]",
            extensions=extensions,
        )
    return lon, lat


def _check_service_area(positions: list[tuple[str, tuple[float, float]]], area: ServiceArea) -> None:
    outside = [(path, xy) for path, xy in positions if not area.contains(*xy)]
    if not outside:
        return
    path, (lon, lat) = outside[0]
    extensions: dict[str, Any] = {"path": path, "position": [lon, lat], "serviceAreaBbox": list(area.bbox)}
    if all(area.contains(y, x) for _, (x, y) in positions):
        extensions["likelySwapped"] = True
        raise CoordinateError(
            "geometry is outside the service area but would be inside it with the axes swapped; "
            "GeoJSON positions must be [longitude, latitude]",
            extensions=extensions,
        )
    raise CoordinateError(
        f"{len(outside)} of {len(positions)} positions are outside the service area", extensions=extensions
    )


def _check_rings(geojson_type: str, coordinates: Any) -> None:
    polygons = [coordinates] if geojson_type == "Polygon" else coordinates
    for p_index, rings in enumerate(polygons):
        if not rings:
            raise _invalid("a polygon needs an exterior ring", path=f"coordinates[{p_index}]")
        for r_index, ring in enumerate(rings):
            path = (
                f"coordinates[{r_index}]"
                if geojson_type == "Polygon"
                else f"coordinates[{p_index}][{r_index}]"
            )
            if len(ring) < 4:
                raise _invalid("a linear ring needs at least four positions", path=path)
            if list(ring[0][:2]) != list(ring[-1][:2]):
                raise _invalid("a linear ring must be closed (first and last positions equal)", path=path)


def _check_lines(geojson_type: str, coordinates: Any) -> None:
    lines = [coordinates] if geojson_type == "LineString" else coordinates
    for index, line in enumerate(lines):
        path = "coordinates" if geojson_type == "LineString" else f"coordinates[{index}]"
        if len(line) < 2:
            raise _invalid("a line needs at least two positions", path=path)


def repair_polygonal(geometry: Geometry) -> Geometry:
    """Valid polygonal part of ``geometry`` (same method as ``meta.repair_polygonal`` in the database)."""
    repaired = shapely.make_valid(geometry, method="structure", keep_collapsed=False)
    polygons = shapely.get_parts(repaired)
    kept = [part for part in polygons if part.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.union_all(kept) if kept else shapely.MultiPolygon()


def parse_geojson_geometry(
    obj: Mapping[str, Any],
    *,
    area: ServiceArea,
    allowed_types: frozenset[str] = GEOJSON_TYPES,
    invalid_polygons: InvalidPolygonPolicy = "reject",
    max_vertices: int = DEFAULT_MAX_VERTICES,
) -> ValidatedGeometry:
    """Validate a GeoJSON geometry object; see the module docstring for the rules."""
    geojson_type = obj.get("type")
    if geojson_type == "GeometryCollection":
        raise _invalid("GeometryCollection is not supported; send one geometry of a single type")
    if not isinstance(geojson_type, str) or geojson_type not in GEOJSON_TYPES:
        raise _invalid(f"unsupported geometry type {geojson_type!r}", allowedTypes=sorted(allowed_types))
    if geojson_type not in allowed_types:
        raise _invalid(
            f"{geojson_type} is not accepted here", allowedTypes=sorted(allowed_types), type=geojson_type
        )
    if "coordinates" not in obj:
        raise _invalid("geometry has no coordinates")
    coordinates = obj["coordinates"]

    positions = [
        (path, _position(path, value))
        for path, value in _positions(coordinates, _DEPTH[geojson_type], "coordinates")
    ]
    if not positions:
        raise _invalid("geometry is empty")
    if len(positions) > max_vertices:
        raise _invalid(f"geometry has {len(positions)} positions; the limit is {max_vertices}")
    if geojson_type in POLYGON_TYPES:
        _check_rings(geojson_type, coordinates)
    elif geojson_type in LINE_TYPES:
        _check_lines(geojson_type, coordinates)
    _check_service_area(positions, area)

    try:
        geometry = shapely.force_2d(shape({"type": geojson_type, "coordinates": coordinates}))
    except (ValueError, TypeError, GEOSException) as exc:
        raise _invalid(f"geometry could not be read: {exc}") from exc
    if geometry.is_empty:
        raise _invalid("geometry is empty")

    if shapely.is_valid(geometry):
        return ValidatedGeometry(geometry)
    reason = str(shapely.is_valid_reason(geometry))
    if geojson_type in POLYGON_TYPES and invalid_polygons != "reject":
        repaired = repair_polygonal(geometry)
        if repaired.is_empty:
            raise _invalid(f"invalid polygon cannot be repaired: {reason}", reason=reason)
        if invalid_polygons == "repair":
            return ValidatedGeometry(repaired, repaired=True, invalid_reason=reason)
        return ValidatedGeometry(geometry, invalid_reason=reason)
    raise _invalid(f"invalid geometry: {reason}", reason=reason)
