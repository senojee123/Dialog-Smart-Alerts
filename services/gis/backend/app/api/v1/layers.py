"""``/geo/v1/layers``: what the platform knows about, and the features of one layer.

The catalogue is the entry point for a client: it names every published layer, the geometry it holds, and
which spatial questions can be asked of it. ``/features`` then reads one layer, filtered by a viewport,
by attributes and - for layers with a validity period - by an instant.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import PrincipalDep, SpatialQueryServiceDep, access_for
from app.api.v1.problems import other_tenant, problem, requires, unavailable
from app.core.access import Permission
from app.schemas.spatial_query import FeatureCollectionOut, FeatureListQuery, LayerCatalogue
from app.spatial.layers import LAYER_CODE_PATTERN

router = APIRouter(tags=["layers"])

CATALOGUE_DESCRIPTION = """
Lists the published layers of the GIS platform: national reference data (`ref.*`, versioned by reference
data release) and the tenant's own operational layers (`ops.*`, subject to row-level security).

For each layer: the geometry types it holds, the CRS features are served in (always EPSG:4326) and the one
distances are measured in (EPSG:5235), and what the query API can do with it - `features`,
`within_distance`, `nearest` and, for layers with areas, `contains`. `filters` and `properties` name the
attribute filters it accepts and the properties its features carry, which is what the other endpoints
validate requests against.
"""

FEATURES_DESCRIPTION = """
Features of one layer as a GeoJSON `FeatureCollection`, filtered and paged.

* **Viewport**: `bbox=minLon,minLat,maxLon,maxLat` (WGS84 degrees) returns what overlaps that box.
* **Attributes**: the filters the layer lists in the catalogue, e.g. `type`, `status`, `level`.
  A filter the layer does not have is rejected rather than ignored.
* **Validity**: layers with a period (risk zones, geofences, fields of view) are read as of `at`,
  by default now.
* **Reference data**: `refDataRelease` pins a published release; by default the current one is used, and
  the answer says which it was.
* **Paging**: pass `nextCursor` back as `cursor` with every other parameter unchanged. `includeGeometry=
  false` returns properties only, which is much smaller for boundary layers.

Operational layers are read for the tenant the request acts for: it sees its own features and those
other tenants shared with it. Reading an operational layer, and searching any layer
by name, is recorded in the audit log.
"""

_FEATURES = "/geo/v1/layers/ref.settlement/features"

FEATURE_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: other_tenant(_FEATURES),
    status.HTTP_404_NOT_FOUND: problem(
        404,
        "layer_not_found",
        "Layer not found",
        "No queryable layer has this code; the catalogue lists the ones that do.",
        _FEATURES,
    ),
    status.HTTP_422_UNPROCESSABLE_CONTENT: problem(
        422,
        "unsupported_filter",
        "Filter is not supported for this layer",
        "A filter the layer does not have (`unsupported_filter`, with `supportedFilters`), a value outside "
        "its allowed set (with `allowedValues`), a malformed `bbox` (`invalid_bbox`), or a cursor from "
        "another query (`invalid_cursor`).",
        _FEATURES,
    ),
    status.HTTP_503_SERVICE_UNAVAILABLE: unavailable(
        _FEATURES,
        "No reference data release is published (`reference_data_unavailable`).",
    ),
}


@router.get(
    "/layers",
    operation_id="listLayers",
    response_model=LayerCatalogue,
    summary="Layer catalogue",
    description=CATALOGUE_DESCRIPTION,
    responses={},
    openapi_extra=requires(Permission.MAP_READ),
)
async def list_layers(
    principal: PrincipalDep, service: SpatialQueryServiceDep, response: Response
) -> LayerCatalogue:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "private, max-age=60"
    return await service.catalogue()


@router.get(
    "/layers/{layer}/features",
    operation_id="listLayerFeatures",
    response_model=FeatureCollectionOut,
    summary="Features of a layer (GeoJSON)",
    description=FEATURES_DESCRIPTION,
    responses=FEATURE_RESPONSES,
    openapi_extra=requires(Permission.MAP_READ),
)
async def list_layer_features(
    layer: Annotated[
        str,
        Path(
            pattern=LAYER_CODE_PATTERN,
            description="Layer code from the catalogue.",
            examples=["ref.settlement"],
        ),
    ],
    params: Annotated[FeatureListQuery, Query()],
    principal: PrincipalDep,
    service: SpatialQueryServiceDep,
    response: Response,
) -> FeatureCollectionOut:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "no-store"
    return await service.features(layer, params, access_for(principal, params.tenant_id))
