"""Version 1 of the GIS API, mounted at ``/geo/v1`` (plan Section 7)."""

from fastapi import APIRouter

from app.api.v1 import (
    assets,
    audit,
    enrichment,
    events,
    exports,
    geofences,
    layers,
    queries,
    releases,
    service_area,
)

API_V1_PREFIX = "/geo/v1"

api_router = APIRouter(prefix=API_V1_PREFIX)
api_router.include_router(service_area.router)
api_router.include_router(layers.router)
api_router.include_router(queries.router)
api_router.include_router(events.router)
api_router.include_router(geofences.router)
api_router.include_router(assets.router)
api_router.include_router(enrichment.router)
api_router.include_router(exports.router)
api_router.include_router(audit.router)
api_router.include_router(releases.router)

__all__ = ["API_V1_PREFIX", "api_router"]
