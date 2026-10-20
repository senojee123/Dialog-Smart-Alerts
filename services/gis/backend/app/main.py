"""FastAPI application factory.

Run with ``uvicorn app.main:create_app --factory``. There is deliberately no module-level ``app``:
building the application requires configuration, and importing this module must not.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import SERVICE_NAME, __version__
from app.api import health
from app.api.deps import AppContainer
from app.api.errors import register_exception_handlers
from app.api.v1 import api_router
from app.core.caller import TENANT_HEADER
from app.core.config import Environment, Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import (
    REQUEST_ID_HEADER,
    BodySizeLimitMiddleware,
    HttpMetrics,
    RequestContextMiddleware,
)
from app.db.engine import create_engine, create_session_factory
from app.schemas.problem import ProblemDetail
from app.services.audit_log import AuditLogService
from app.services.enrichment import GeoContextLimits, GeoContextService
from app.services.migrations import load_migration_heads
from app.services.operational import OperationalService
from app.services.readiness import ReadinessService
from app.services.release_catalogue import ReleaseCatalogue
from app.services.spatial_query import SpatialQueryService
from app.spatial import crs
from app.spatial.service_area import ServiceArea

logger = logging.getLogger(__name__)

OPENAPI_DESCRIPTION = """
Geospatial intelligence for the geo-aware event platform: authoritative PostGIS storage,
geo-context enrichment and spatial queries for Sri Lanka.

**What it offers.** A layer catalogue and the features of each layer, generic spatial queries (within a
distance, nearest, containment), reverse geocoding, event locations by time and area, geo-context
enrichment for a single event, and management of a tenant's own geofences, sites and device placements.

**Boundary.** This service produces spatial facts only. It does not send alerts, choose notification
recipients or deliver messages; see ARCHITECTURE.md.

**Conventions.** Coordinates are GeoJSON (RFC 7946), WGS84 `[longitude, latitude]`. Distances are in
metres, computed in SLD99 / Sri Lanka Grid 1999 (EPSG:5235). Errors are RFC 9457 problem details
(`application/problem+json`); the `type` URN names the error.

**Access.** The GIS runs as an instance of the main platform, which owns users and sign-in, and is reached
only through the platform. It checks no credentials. A request acts for the tenant (organisation) in its
`X-GIS-Tenant-Id` header, else for the platform's organisation (`GIS_TENANT_ID`); PostgreSQL row-level
security keeps each tenant's data apart. Searches, reads of operational data and events, exports and
changes are recorded in an append-only audit log (`GET /geo/v1/audit/entries`).
"""


def enrichment_limits(settings: Settings) -> GeoContextLimits:
    return GeoContextLimits(
        settlement_radius_m=settings.enrichment_settlement_radius_m,
        road_radius_m=settings.enrichment_road_radius_m,
        device_radius_m=settings.enrichment_device_radius_m,
        device_limit=settings.enrichment_device_limit,
    )


def _load_heads(settings: Settings) -> frozenset[str] | None:
    try:
        return load_migration_heads(settings.alembic_config_path)
    except Exception:
        logger.exception("could not load migration scripts; readiness will fail")
        return None


def _document_problem_details(app: FastAPI) -> None:
    """Add the RFC 9457 ``ProblemDetail`` schema that error responses reference."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title,
                version=app.version,
                openapi_version=app.openapi_version,
                description=app.description,
                routes=app.routes,
            )
            components = schema.setdefault("components", {}).setdefault("schemas", {})
            components["ProblemDetail"] = ProblemDetail.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def _serve_static_files(app: FastAPI, settings: Settings) -> None:
    """The built map application (/app) and the basemaps (/basemap), when configured (the platform image).

    The main platform proxies them with the API, so it serves one GIS service. Starlette answers HTTP range
    requests, which PMTiles basemaps are read with.
    """
    for path, directory, html in (
        ("/app", settings.web_dir, True),
        ("/basemap", settings.basemap_dir, False),
    ):
        if directory is None:
            continue
        if directory.is_dir():
            app.mount(path, StaticFiles(directory=directory, html=html), name=path.strip("/"))
        else:
            logger.warning(
                "static directory not found; not serving it",
                extra={"path": path, "directory": str(directory)},
            )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.database_url()  # fail fast if runtime database credentials are missing
    configure_logging(settings.log_level, settings.log_format)
    if settings.env is not Environment.PRODUCTION:
        # The production guards (database TLS, separate logins, no wildcard CORS) apply only with
        # GIS_ENV=production; a deployment that forgets it must at least say so.
        logger.warning(
            "running without production safeguards; set GIS_ENV=production in deployments",
            extra={"environment": settings.env.value},
        )
    metrics = HttpMetrics() if settings.metrics_enabled else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        service_area = ServiceArea.from_bbox(settings.service_area_bbox)
        limits = enrichment_limits(settings)
        container = AppContainer(
            settings=settings,
            engine=engine,
            session_factory=session_factory,
            service_area=service_area,
            readiness=ReadinessService(engine, settings, _load_heads(settings)),
            geo_context=GeoContextService(session_factory, service_area, limits),
            spatial_query=SpatialQueryService(
                session_factory, service_area, limits, export_max_features=settings.export_max_features
            ),
            operational=OperationalService(session_factory, service_area),
            audit_log=AuditLogService(session_factory),
            releases=ReleaseCatalogue(session_factory),
        )
        app.state.container = container
        logger.info(
            "service starting",
            extra={
                "service": SERVICE_NAME,
                "version": __version__,
                "environment": settings.env.value,
                "db_host": settings.db_host,
                "db_name": settings.db_name,
                "db_user": settings.db_app_user,
                "service_area_bbox": list(settings.service_area_bbox),
                "proj_version": crs.proj_version(),
                "tenant_id": settings.tenant_id,
            },
        )
        try:
            yield
        finally:
            await engine.dispose()
            logger.info("service stopped")

    docs_url = "/docs" if settings.docs_enabled else None
    app = FastAPI(
        title="GIS Core Service",
        version=__version__,
        description=OPENAPI_DESCRIPTION,
        root_path=settings.api_root_path,
        docs_url=docs_url,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router)
    _document_problem_details(app)
    _serve_static_files(app, settings)
    if metrics is not None:
        registry = metrics.registry

        @app.get("/metrics", include_in_schema=False)
        async def prometheus_metrics() -> Response:
            # Scrape endpoint for Prometheus. Expose it on the internal network only.
            return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", REQUEST_ID_HEADER, TENANT_HEADER, "Idempotency-Key"],
            expose_headers=[REQUEST_ID_HEADER],
            max_age=600,
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    # Added last so it wraps everything, including CORS preflight responses and error handlers.
    app.add_middleware(RequestContextMiddleware, metrics=metrics)
    return app
