"""``/geo/v1/layers/{layer}/export`` and ``/geo/v1/events/export``: a selection as one GeoJSON file.

An export is the complete selection or nothing: a selection larger than ``GIS_EXPORT_MAX_FEATURES`` is
refused (422 ``export_too_large``) instead of being cut short, because a file that silently holds part of
an area would be mistaken for all of it. Every export is recorded in the audit log with what was selected
and how many features left the service.

Reference data leaves the platform only when its licence allows it: an export of a layer built from a
source whose licence forbids redistribution is refused (403 ``export_not_permitted``), and an export of
reference data carries the attribution its sources require (``attribution``).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Query, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import PrincipalDep, SpatialQueryServiceDep, access_for
from app.api.v1.problems import forbidden, problem, requires
from app.core.access import Permission
from app.schemas.spatial_query import (
    EVENT_MAX_WINDOW_DAYS,
    EventExportOut,
    EventExportQuery,
    FeatureExportOut,
    FeatureExportQuery,
)
from app.spatial.layers import LAYER_CODE_PATTERN

router = APIRouter(tags=["exports"])

GEOJSON_MEDIA_TYPE: Final = "application/geo+json"
_UNSAFE_FILENAME = re.compile(r"[^a-z0-9_-]+")


class GeoJsonResponse(JSONResponse):
    media_type = GEOJSON_MEDIA_TYPE


def _attachment(response: Response, *parts: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = "-".join(_UNSAFE_FILENAME.sub("-", part.lower()) for part in (*parts, stamp))
    response.headers["Content-Disposition"] = f'attachment; filename="{name}.geojson"'
    response.headers["Cache-Control"] = "no-store"


def _responses(instance: str) -> dict[int | str, dict[str, Any]]:
    return {
        status.HTTP_200_OK: {"content": {GEOJSON_MEDIA_TYPE: {}}},
        status.HTTP_403_FORBIDDEN: forbidden(
            instance,
            "The licence of a source of the layer does not allow its data to leave the platform "
            "(`export_not_permitted`, with `sources`), or `tenantId` names a tenant other than the one the "
            "request acts for.",
        ),
        status.HTTP_422_UNPROCESSABLE_CONTENT: problem(
            422,
            "export_too_large",
            "Export is larger than allowed",
            "The selection holds more features than one export may (`export_too_large`, with `maxFeatures`): "
            "narrow the area, the filters or the window. Also: an unsupported filter or a malformed `bbox`.",
            instance,
        ),
    }


@router.get(
    "/layers/{layer}/export",
    operation_id="exportLayerFeatures",
    response_model=FeatureExportOut,
    response_class=GeoJsonResponse,
    summary="Export features of a layer (GeoJSON file)",
    description="The features of one layer that match the selection - viewport, filters, `at`, release - "
    "as one GeoJSON file (`Content-Disposition: attachment`), never paged. Operational layers export the "
    "tenant's own features and those shared with it. Reference layers carry the attribution their sources "
    "require, and are refused when a source's licence forbids redistribution. Recorded in the audit log.",
    responses=_responses("/geo/v1/layers/ops.geofence/export"),
    openapi_extra=requires(Permission.DATA_EXPORT, Permission.MAP_READ),
)
async def export_layer_features(
    layer: Annotated[
        str,
        Path(pattern=LAYER_CODE_PATTERN, description="Layer code from the catalogue.", examples=["ops.site"]),
    ],
    params: Annotated[FeatureExportQuery, Query()],
    principal: PrincipalDep,
    service: SpatialQueryServiceDep,
    response: Response,
) -> FeatureExportOut:
    principal.require(Permission.DATA_EXPORT, Permission.MAP_READ)
    export = await service.export_features(layer, params, access_for(principal, params.tenant_id))
    _attachment(response, layer.replace(".", "-"), *([export.tenant_id] if export.tenant_id else []))
    return export


@router.get(
    "/events/export",
    operation_id="exportEvents",
    response_model=EventExportOut,
    response_class=GeoJsonResponse,
    summary="Export event locations (GeoJSON file)",
    description="Every event location of the window that matches the filters of `GET /geo/v1/events`, as "
    f"one GeoJSON file, newest first. The window may not exceed {EVENT_MAX_WINDOW_DAYS} days. Recorded in "
    "the audit log.",
    responses=_responses("/geo/v1/events/export"),
    openapi_extra=requires(Permission.DATA_EXPORT, Permission.EVENTS_READ),
)
async def export_events(
    params: Annotated[EventExportQuery, Query()],
    principal: PrincipalDep,
    service: SpatialQueryServiceDep,
    response: Response,
) -> EventExportOut:
    principal.require(Permission.DATA_EXPORT, Permission.EVENTS_READ)
    export = await service.export_events(params, access_for(principal, params.tenant_id))
    _attachment(response, "events", *([export.tenant_id] if export.tenant_id else []))
    return export
