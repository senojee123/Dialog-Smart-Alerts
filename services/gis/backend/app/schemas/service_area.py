"""GeoJSON representation of the configured service area."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel

Position = tuple[float, float]


class PolygonGeometry(ApiModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Position]]


class ServiceAreaProperties(ApiModel):
    bbox: tuple[float, float, float, float] = Field(description="min_lon, min_lat, max_lon, max_lat (WGS84)")
    crs: Literal["EPSG:4326"] = "EPSG:4326"
    metric_crs: Literal["EPSG:5235"] = "EPSG:5235"
    description: str


class ServiceAreaFeature(ApiModel):
    """GeoJSON Feature (RFC 7946). Coordinates are WGS84 ``[longitude, latitude]``."""

    type: Literal["Feature"] = "Feature"
    geometry: PolygonGeometry
    properties: ServiceAreaProperties
