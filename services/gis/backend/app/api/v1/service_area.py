"""``GET /geo/v1/service-area``: the area this deployment accepts positions for.

Clients use it to set the initial map view and to pre-validate input. It is configuration, not
reference data, and is served without touching the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import ServiceAreaDep
from app.schemas.service_area import PolygonGeometry, ServiceAreaFeature, ServiceAreaProperties

router = APIRouter(tags=["service area"])

DESCRIPTION = (
    "Positions outside this box are rejected. Default: EPSG:5235 area of use (Sri Lanka onshore) "
    "widened by 0.2 degrees for nearshore waters."
)


@router.get(
    "/service-area",
    response_model=ServiceAreaFeature,
    summary="Service area (GeoJSON Feature, WGS84)",
    response_model_by_alias=True,
)
async def get_service_area(area: ServiceAreaDep, response: Response) -> ServiceAreaFeature:
    response.headers["Cache-Control"] = "public, max-age=300"
    geometry = area.to_geojson_geometry()
    return ServiceAreaFeature(
        geometry=PolygonGeometry(coordinates=geometry["coordinates"]),
        properties=ServiceAreaProperties(bbox=area.bbox, description=DESCRIPTION),
    )
