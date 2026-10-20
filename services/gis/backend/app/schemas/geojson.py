"""GeoJSON geometry objects at the API boundary (RFC 7946, WGS84, ``[longitude, latitude]``).

The schema checks the envelope (type and nesting). Coordinate ranges, the service area, ring closure
and OGC validity are checked by :func:`app.spatial.geometry.parse_geojson_geometry`, which needs the
deployment's service area.
"""

from __future__ import annotations

from typing import Any, Literal

import shapely
from pydantic import Field
from shapely import Geometry
from shapely.geometry import mapping

from app.schemas.base import ApiModel

GeoJsonGeometryType = Literal[
    "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"
]


class GeoJsonGeometry(ApiModel):
    type: GeoJsonGeometryType
    coordinates: list[Any] = Field(
        description="Positions as [longitude, latitude] (WGS84); nesting depends on the type.",
        min_length=1,
    )

    def as_mapping(self) -> dict[str, Any]:
        return {"type": self.type, "coordinates": self.coordinates}

    @classmethod
    def from_shapely(cls, geometry: Geometry, *, precision: int = 7) -> GeoJsonGeometry:
        """GeoJSON for output, coordinates rounded to ``precision`` decimals (7 is about 1 cm)."""
        rounded = shapely.transform(geometry, lambda coords: coords.round(precision))
        data = mapping(rounded)
        return cls.model_validate({"type": data["type"], "coordinates": _as_lists(data["coordinates"])})


def _as_lists(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [_as_lists(item) for item in value]
    return value
