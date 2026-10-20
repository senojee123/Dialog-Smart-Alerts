"""``/geo/v1/geofences``: the areas a tenant maintains.

A geofence is a named area with a validity period. The GIS service reports that an event lies inside one
(in the event's geo-context) and answers spatial questions about it; it does not act on that fact.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import AccessDep, OperationalServiceDep, PrincipalDep, access_for
from app.api.v1.problems import forbidden, other_tenant, problem, requires
from app.core.access import Permission
from app.schemas.operational import (
    GeofenceIn,
    GeofenceListOut,
    GeofenceOut,
    GeofenceUpdate,
    OperationalListQuery,
)

router = APIRouter(tags=["geofences"])

_GEOFENCES = "/geo/v1/geofences"
_GEOFENCE = "/geo/v1/geofences/{id}"

LIST_DESCRIPTION = """
The geofences this tenant can see: its own, and those other tenants shared with it.

Filter by `status`, `kind` (polygon, circle, corridor), `bbox`, `nameContains`, `at` (in effect at that
instant) and `ownedOnly`. Paged with `nextCursor`.
"""

CREATE_DESCRIPTION = """
Creates a geofence from the geometry you define:

* `polygon`: a Polygon or MultiPolygon
* `circle`: a Point centre and `radiusM` (at most 50 km)
* `corridor`: a LineString or MultiLineString centre line and `radiusM` as the half-width (at most 5 km)

The definition is stored as given, in WGS84, after being validated: it must be geometrically valid and lie
inside the service area. The database derives the search geometry from it in EPSG:5235, and hits on circles
and corridors are tested against the definition and the radius, so they are exact.

Only `active` geofences produce geo-context hits, and only while `effectiveDuring` contains the event's
observation time. `sharingPolicy` decides who else may read the geofence; only the owning tenant can ever
change it.
"""

REPLACE_DESCRIPTION = """
Replaces a geofence with the representation given, based on the `version` you read. If it has changed since,
the request is refused with 409 and the current version - read it again and retry.

Every change increments the version. Stored geo-context hits name the version they were computed against,
so an earlier hit stays interpretable after the geofence is changed.
"""

DELETE_DESCRIPTION = """
Retires a geofence: its status becomes `archived`, so it stops producing hits but stays readable, which keeps
geo-context hits that name it meaningful.

`purge=true` deletes it irreversibly - for a geofence created by mistake. `version` makes either operation
conditional on the geofence not having changed since it was read.
"""

_COMMON: dict[int | str, dict[str, Any]] = {}
_NOT_FOUND = problem(
    404,
    "geofence_not_found",
    "Geofence not found",
    "No geofence with this id is visible to the tenant.",
    _GEOFENCE,
)
_WRITE_FORBIDDEN = forbidden(
    _GEOFENCE,
    "The geofence belongs to another tenant and is only shared for reading (`not_owner`), or `tenantId` "
    "names a tenant other than the one the request acts for.",
)
_INVALID = problem(
    422,
    "invalid_geometry",
    "Geometry is not acceptable",
    "The definition does not match the kind, is geometrically invalid, is empty, or lies outside the service "
    "area (`invalid_geometry`, `invalid_coordinate`).",
    _GEOFENCES,
)
_CONFLICT = problem(
    409,
    "version_conflict",
    "Object has changed since it was read",
    "The geofence has changed since `version` (`version_conflict`, with `currentVersion`), or `externalId` "
    "is already used by another geofence of this tenant (`external_id_in_use`).",
    _GEOFENCE,
)


@router.get(
    "/geofences",
    operation_id="listGeofences",
    response_model=GeofenceListOut,
    summary="List geofences",
    description=LIST_DESCRIPTION,
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: other_tenant(_GEOFENCES),
    },
    openapi_extra=requires(Permission.MAP_READ),
)
async def list_geofences(
    params: Annotated[OperationalListQuery, Query()],
    principal: PrincipalDep,
    service: OperationalServiceDep,
    response: Response,
) -> GeofenceListOut:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "no-store"
    return await service.geofences(access_for(principal, params.tenant_id), params)


@router.post(
    "/geofences",
    operation_id="createGeofence",
    response_model=GeofenceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a geofence",
    description=CREATE_DESCRIPTION,
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: _WRITE_FORBIDDEN,
        status.HTTP_409_CONFLICT: _CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID,
    },
    openapi_extra=requires(Permission.GEOFENCES_WRITE),
)
async def create_geofence(
    body: GeofenceIn,
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
    response: Response,
) -> GeofenceOut:
    principal.require(Permission.GEOFENCES_WRITE)
    geofence = await service.create_geofence(access, body)
    response.headers["Location"] = f"/geo/v1/geofences/{geofence.id}"
    return geofence


@router.get(
    "/geofences/{geofence_id}",
    operation_id="getGeofence",
    response_model=GeofenceOut,
    summary="Read a geofence",
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: other_tenant(_GEOFENCE),
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
    },
    openapi_extra=requires(Permission.MAP_READ),
)
async def get_geofence(
    geofence_id: Annotated[uuid.UUID, Path(description="Geofence id.")],
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
    response: Response,
) -> GeofenceOut:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "no-store"
    return await service.geofence(access, geofence_id)


@router.put(
    "/geofences/{geofence_id}",
    operation_id="replaceGeofence",
    response_model=GeofenceOut,
    summary="Replace a geofence",
    description=REPLACE_DESCRIPTION,
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: _WRITE_FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
        status.HTTP_409_CONFLICT: _CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _INVALID,
    },
    openapi_extra=requires(Permission.GEOFENCES_WRITE),
)
async def replace_geofence(
    geofence_id: Annotated[uuid.UUID, Path(description="Geofence id.")],
    body: GeofenceUpdate,
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
) -> GeofenceOut:
    principal.require(Permission.GEOFENCES_WRITE)
    return await service.replace_geofence(access, geofence_id, body)


@router.delete(
    "/geofences/{geofence_id}",
    operation_id="deleteGeofence",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive (or purge) a geofence",
    description=DELETE_DESCRIPTION,
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: _WRITE_FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND,
        status.HTTP_409_CONFLICT: _CONFLICT,
    },
    openapi_extra=requires(Permission.GEOFENCES_WRITE, purge=Permission.DATA_PURGE),
)
async def delete_geofence(
    geofence_id: Annotated[uuid.UUID, Path(description="Geofence id.")],
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
    purge: Annotated[
        bool,
        Query(description="Delete the geofence irreversibly instead of archiving it."),
    ] = False,
    version: Annotated[
        int | None,
        Query(ge=1, description="Only if the geofence is still at this version."),
    ] = None,
) -> None:
    principal.require(Permission.GEOFENCES_WRITE)
    if purge:
        principal.require(Permission.DATA_PURGE)
    await service.delete_geofence(access, geofence_id, purge=purge, version=version)
