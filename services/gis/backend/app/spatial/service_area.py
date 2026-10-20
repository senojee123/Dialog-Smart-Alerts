"""The geographic area this deployment accepts positions for (plan Section 5.2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely import Polygon, box


@dataclass(frozen=True, slots=True)
class ServiceArea:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @classmethod
    def from_bbox(cls, bbox: tuple[float, float, float, float]) -> ServiceArea:
        return cls(*bbox)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)

    def contains(self, lon: float, lat: float) -> bool:
        """Inclusive containment test in WGS84 degrees."""
        return self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat

    def to_polygon(self) -> Polygon:
        return box(self.min_lon, self.min_lat, self.max_lon, self.max_lat, ccw=True)

    def to_geojson_geometry(self) -> dict[str, Any]:
        exterior = [[float(x), float(y)] for x, y in self.to_polygon().exterior.coords]
        return {"type": "Polygon", "coordinates": [exterior]}
