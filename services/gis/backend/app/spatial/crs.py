"""Coordinate reference system conventions (ADR-02).

* Canonical storage and API exchange: WGS84, EPSG:4326, axis order ``[longitude, latitude]``.
* Metric work (distances, buffers, areas): SLD99 / Sri Lanka Grid 1999, EPSG:5235.
* Map tiles: Web Mercator, EPSG:3857.

WGS84 -> SLD99 is a datum change. PROJ selects "SLD99 to WGS 84 (1)", whose published accuracy is
14 m. That uncertainty is a near-constant offset across a local area, so distances between points
transformed the same way stay accurate; it only matters when mixing SLD99-surveyed data with
WGS84 positions (see ARCHITECTURE.md, "Coordinate systems").
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Final

import pyproj
from pyproj import Transformer
from shapely import Geometry
from shapely.ops import transform as shapely_transform

WGS84: Final = 4326
SLD99_GEOGRAPHIC: Final = 5233
SLD99_GRID: Final = 5235
WEB_MERCATOR: Final = 3857

CANONICAL_SRID: Final = WGS84
METRIC_SRID: Final = SLD99_GRID
REQUIRED_SRIDS: Final = frozenset({WGS84, SLD99_GRID, WEB_MERCATOR})

# pyproj Transformer objects must not be shared across threads; keep one cache per thread.
_local = threading.local()


def get_transformer(source_srid: int, target_srid: int) -> Transformer:
    cache: dict[tuple[int, int], Transformer] | None = getattr(_local, "transformers", None)
    if cache is None:
        cache = {}
        _local.transformers = cache
    key = (source_srid, target_srid)
    transformer = cache.get(key)
    if transformer is None:
        transformer = Transformer.from_crs(source_srid, target_srid, always_xy=True)
        cache[key] = transformer
    return transformer


def _projector(source_srid: int, target_srid: int) -> Callable[..., tuple[float, float]]:
    transformer = get_transformer(source_srid, target_srid)

    def project(x: float, y: float, z: float | None = None) -> tuple[float, float]:
        return transformer.transform(x, y)

    return project


def to_metric(geometry: Geometry) -> Geometry:
    """WGS84 geometry -> SLD99 grid geometry (metres)."""
    return shapely_transform(_projector(WGS84, SLD99_GRID), geometry)


def to_wgs84(geometry: Geometry) -> Geometry:
    """SLD99 grid geometry (metres) -> WGS84 geometry."""
    return shapely_transform(_projector(SLD99_GRID, WGS84), geometry)


def wgs84_to_metric_xy(lon: float, lat: float) -> tuple[float, float]:
    easting, northing = get_transformer(WGS84, SLD99_GRID).transform(lon, lat)
    return float(easting), float(northing)


def proj_version() -> str:
    return str(pyproj.proj_version_str)
