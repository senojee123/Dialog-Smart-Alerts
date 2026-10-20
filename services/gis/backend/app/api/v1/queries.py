"""``/geo/v1/query/*`` and ``/geo/v1/reverse``: the reusable spatial questions.

Three questions cover most of what callers need, on any queryable layer:

* ``within-distance`` - which objects are within N metres of this geometry
* ``nearest`` - which objects are closest to it
* ``contains`` - which areas contain it

They are deliberately generic. The GIS service answers where things are; deciding what to do with the
answer - and in particular who to tell - belongs to the services that use it (ADR-0012).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AccessDep, PrincipalDep, SpatialQueryServiceDep
from app.api.v1.problems import other_tenant, problem, requires, unavailable
from app.core.access import Permission
from app.schemas.reference_data import RELEASE_CODE_PATTERN
from app.schemas.spatial_query import (
    ContainsQuery,
    FeatureCollectionOut,
    NearestQuery,
    ReverseGeocodeOut,
    WithinDistanceQuery,
)

router = APIRouter(tags=["spatial queries"])

CONVENTIONS = """
* **Geometry**: GeoJSON, WGS84, `[longitude, latitude]`; Point, LineString, Polygon and the Multi forms.
  Positions outside Sri Lanka's service area are rejected, and when the swapped axes would be inside it the
  problem says `likelySwapped`. A `crs` member is not accepted (RFC 7946 removed it); the optional `crs`
  field may state a WGS84 identifier.
* **Distances**: metres, computed in EPSG:5235 (SLD99), rounded to 0.01 m in the answer. Thresholds are
  inclusive: a feature exactly at the distance is included.
* **Scope**: reference layers are read from a published release (`refDataRelease`, default: the current
  one), which the answer names. Operational layers need a tenant and show only what it may see.
"""

WITHIN_DISTANCE_DESCRIPTION = (
    """
Objects of one layer within `distanceM` of a geometry, nearest first, with `distanceM` on each feature.

Distance is measured to the feature itself - the edge of a settlement footprint, the line of a road, the
circle of a geofence - not to a centroid or a bounding box.
"""
    + CONVENTIONS
    + """
Large answers are paged with `nextCursor`. For a handful of nearest objects, `/query/nearest` is cheaper.
"""
)

NEAREST_DESCRIPTION = (
    """
The `limit` nearest objects of one layer, nearest first, bounded by `maxDistanceM`.

The bound is what keeps the search on the spatial index, and it is also what makes the answer meaningful:
without it, "nearest" can be hundreds of kilometres away.
"""
    + CONVENTIONS
)

CONTAINS_DESCRIPTION = (
    """
Areas of one layer that contain a geometry: point-in-polygon, and the same question for lines and areas.

`mode=covers` (default) returns areas that contain the whole geometry, boundary inclusive - a point exactly
on a boundary counts as inside. `mode=intersects` returns areas that share any point with it. Each feature
carries `relation`: `within` when the whole geometry lies inside, `intersects` when it crosses the
boundary.

Circle and corridor geofences are tested against their definition and radius, so a hit is exact rather
than an approximation of the stored search polygon.
"""
    + CONVENTIONS
)

REVERSE_DESCRIPTION = """
Where a position is: the administrative hierarchy (province, district, DS division, GN division), the
nearest settlement with its distance, and the nearest road with its distance.

Reference data only - the answer is the same for every tenant, and nothing is stored. Distances are metres
in EPSG:5235. `missingLayers` names reference layers that hold no features in the release, so an empty
answer for one of them is not mistaken for "nothing is there".
"""

_QUERY = "/geo/v1/query/within-distance"
_REVERSE = "/geo/v1/reverse"


def _query_responses(instance: str) -> dict[int | str, dict[str, Any]]:
    return {
        status.HTTP_403_FORBIDDEN: other_tenant(instance),
        status.HTTP_404_NOT_FOUND: problem(
            404,
            "layer_not_found",
            "Layer not found",
            "`target` is not a queryable layer; `GET /geo/v1/layers` lists the ones that are.",
            instance,
        ),
        status.HTTP_422_UNPROCESSABLE_CONTENT: problem(
            422,
            "invalid_geometry",
            "Geometry is not acceptable",
            "Invalid or empty geometry (`invalid_geometry`), positions outside WGS84 or the service area "
            "(`invalid_coordinate`), an unsupported CRS, a filter the layer does not have "
            "(`unsupported_filter`), a question the layer cannot answer (`unsupported_query`), or a cursor "
            "from another query (`invalid_cursor`).",
            instance,
        ),
        status.HTTP_503_SERVICE_UNAVAILABLE: unavailable(
            instance,
            "No reference data release is published (`reference_data_unavailable`).",
        ),
    }


@router.post(
    "/query/within-distance",
    operation_id="queryWithinDistance",
    response_model=FeatureCollectionOut,
    summary="Objects within a distance of a geometry",
    description=WITHIN_DISTANCE_DESCRIPTION,
    responses=_query_responses(_QUERY),
    openapi_extra=requires(Permission.SPATIAL_QUERY),
)
async def query_within_distance(
    query: WithinDistanceQuery,
    principal: PrincipalDep,
    access: AccessDep,
    service: SpatialQueryServiceDep,
    response: Response,
) -> FeatureCollectionOut:
    principal.require(Permission.SPATIAL_QUERY)
    response.headers["Cache-Control"] = "no-store"
    return await service.within_distance(query, access)


@router.post(
    "/query/nearest",
    operation_id="queryNearest",
    response_model=FeatureCollectionOut,
    summary="Nearest objects to a geometry",
    description=NEAREST_DESCRIPTION,
    responses=_query_responses("/geo/v1/query/nearest"),
    openapi_extra=requires(Permission.SPATIAL_QUERY),
)
async def query_nearest(
    query: NearestQuery,
    principal: PrincipalDep,
    access: AccessDep,
    service: SpatialQueryServiceDep,
    response: Response,
) -> FeatureCollectionOut:
    principal.require(Permission.SPATIAL_QUERY)
    response.headers["Cache-Control"] = "no-store"
    return await service.nearest(query, access)


@router.post(
    "/query/contains",
    operation_id="queryContains",
    response_model=FeatureCollectionOut,
    summary="Areas that contain a geometry",
    description=CONTAINS_DESCRIPTION,
    responses=_query_responses("/geo/v1/query/contains"),
    openapi_extra=requires(Permission.SPATIAL_QUERY),
)
async def query_contains(
    query: ContainsQuery,
    principal: PrincipalDep,
    access: AccessDep,
    service: SpatialQueryServiceDep,
    response: Response,
) -> FeatureCollectionOut:
    principal.require(Permission.SPATIAL_QUERY)
    response.headers["Cache-Control"] = "no-store"
    return await service.contains(query, access)


@router.get(
    "/reverse",
    operation_id="reverseGeocode",
    response_model=ReverseGeocodeOut,
    summary="Reverse geocode a position",
    description=REVERSE_DESCRIPTION,
    responses={
        status.HTTP_403_FORBIDDEN: other_tenant(_REVERSE),
        status.HTTP_404_NOT_FOUND: problem(
            404,
            "release_not_found",
            "Reference data release not found",
            "The requested `refDataRelease` does not exist.",
            _REVERSE,
        ),
        status.HTTP_422_UNPROCESSABLE_CONTENT: problem(
            422,
            "invalid_coordinate",
            "Coordinate is not acceptable",
            "The position is outside WGS84 bounds or the service area (`invalid_coordinate`, with "
            "`likelySwapped` when the axes look swapped), or the release is a draft "
            "(`release_not_usable`).",
            _REVERSE,
        ),
        status.HTTP_503_SERVICE_UNAVAILABLE: unavailable(
            _REVERSE, "No reference data release is published (`reference_data_unavailable`)."
        ),
    },
    openapi_extra=requires(Permission.MAP_READ),
)
async def reverse_geocode(
    principal: PrincipalDep,
    access: AccessDep,
    service: SpatialQueryServiceDep,
    response: Response,
    lon: Annotated[
        float, Query(ge=-180, le=180, description="Longitude in WGS84 degrees.", examples=[80.7513])
    ],
    lat: Annotated[float, Query(ge=-90, le=90, description="Latitude in WGS84 degrees.", examples=[8.0342])],
    ref_data_release: Annotated[
        str | None,
        Query(
            alias="refDataRelease",
            pattern=RELEASE_CODE_PATTERN,
            description="Resolve against this published release instead of the current one.",
        ),
    ] = None,
) -> ReverseGeocodeOut:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "private, max-age=60"
    return await service.reverse_geocode(lon, lat, access, ref_data_release)
