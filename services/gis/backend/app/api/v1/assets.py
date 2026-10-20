"""``/geo/v1/sites`` and ``/geo/v1/devices/{id}/placement``: where a tenant's installations are.

Sites are the fixed places a tenant maintains; a device placement is where one camera or sensor is, and
what it observes from there. Both are spatial records: they say where something is, not what it does.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response, status

from app.api.deps import AccessDep, OperationalServiceDep, PrincipalDep, access_for
from app.api.v1.problems import forbidden, other_tenant, problem, requires
from app.core.access import Permission
from app.schemas.operational import (
    DevicePlacementIn,
    DevicePlacementOut,
    OperationalListQuery,
    SiteIn,
    SiteListOut,
    SiteOut,
    SiteUpdate,
)

router = APIRouter(tags=["sites and devices"])

_SITES = "/geo/v1/sites"
_SITE = "/geo/v1/sites/{id}"
_PLACEMENT = "/geo/v1/devices/{id}/placement"

SITE_LIST_DESCRIPTION = """
The sites this tenant can see: its own, and those other tenants shared with it. Filter by `status`,
`siteType`, `bbox`, `nameContains` and `ownedOnly`; paged with `nextCursor`.
"""

PLACEMENT_GET_DESCRIPTION = """
Where a device is: its position, the site it belongs to, its mounting height, and the field of view in
effect - by default now, or at `at`.

A modelled field of view is the sector the database computes from bearing, angle and range; a surveyed one
is the area that was supplied. The geometry returned is the observed area in WGS84.
"""

PLACEMENT_PUT_DESCRIPTION = """
Records where a device is. The identifier in the path is the device's id, which you choose (a UUID):

* the device does not exist yet: it is registered with that id and the response is 201
* it exists: its placement is replaced and the response is 200. Send the `version` you read; if the device
  has changed since, the request is refused with 409

Sending `fieldOfView` closes the period in effect now and starts a new one with the values given. Moving a
device keeps its open modelled field of view aligned with the new position - the database recomputes the
sector - while closed periods keep the geometry they were recorded with.

Only the owning tenant can change a placement, even for a device shared with others for reading.
"""

_COMMON: dict[int | str, dict[str, Any]] = {}
_SITE_NOT_FOUND = problem(
    404, "site_not_found", "Site not found", "No site with this id is visible to the tenant.", _SITE
)
_DEVICE_NOT_FOUND = problem(
    404,
    "device_not_found",
    "Device not found",
    "No device with this id is visible to the tenant.",
    _PLACEMENT,
)
_WRITE_FORBIDDEN = forbidden(
    _SITE,
    "The object belongs to another tenant and is only shared for reading (`not_owner`), or `tenantId` names "
    "a tenant other than the one the request acts for.",
)
_POSITION_INVALID = problem(
    422,
    "invalid_coordinate",
    "Coordinate is not acceptable",
    "The position is not a Point, lies outside WGS84 bounds or the service area (`invalid_coordinate`, with "
    "`likelySwapped` when the axes look swapped), or `siteId` does not name a site of this tenant "
    "(`unknown_site`).",
    _SITE,
)
_CONFLICT = problem(
    409,
    "version_conflict",
    "Object has changed since it was read",
    "The object has changed since `version` (`version_conflict`, with `currentVersion`), `externalId` is "
    "already used (`external_id_in_use`), or the new field of view overlaps a recorded period "
    "(`field_of_view_overlap`).",
    _SITE,
)


@router.get(
    "/sites",
    operation_id="listSites",
    response_model=SiteListOut,
    summary="List sites",
    description=SITE_LIST_DESCRIPTION,
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: other_tenant(_SITES),
    },
    openapi_extra=requires(Permission.MAP_READ),
)
async def list_sites(
    params: Annotated[OperationalListQuery, Query()],
    principal: PrincipalDep,
    service: OperationalServiceDep,
    response: Response,
) -> SiteListOut:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "no-store"
    return await service.sites(access_for(principal, params.tenant_id), params)


@router.post(
    "/sites",
    operation_id="createSite",
    response_model=SiteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a site",
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: _WRITE_FORBIDDEN,
        status.HTTP_409_CONFLICT: _CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _POSITION_INVALID,
    },
    openapi_extra=requires(Permission.ASSETS_WRITE),
)
async def create_site(
    body: SiteIn,
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
    response: Response,
) -> SiteOut:
    principal.require(Permission.ASSETS_WRITE)
    site = await service.create_site(access, body)
    response.headers["Location"] = f"/geo/v1/sites/{site.id}"
    return site


@router.get(
    "/sites/{site_id}",
    operation_id="getSite",
    response_model=SiteOut,
    summary="Read a site",
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: other_tenant(_SITE),
        status.HTTP_404_NOT_FOUND: _SITE_NOT_FOUND,
    },
    openapi_extra=requires(Permission.MAP_READ),
)
async def get_site(
    site_id: Annotated[uuid.UUID, Path(description="Site id.")],
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
    response: Response,
) -> SiteOut:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "no-store"
    return await service.site(access, site_id)


@router.put(
    "/sites/{site_id}",
    operation_id="replaceSite",
    response_model=SiteOut,
    summary="Replace a site",
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: _WRITE_FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _SITE_NOT_FOUND,
        status.HTTP_409_CONFLICT: _CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _POSITION_INVALID,
    },
    openapi_extra=requires(Permission.ASSETS_WRITE),
)
async def replace_site(
    site_id: Annotated[uuid.UUID, Path(description="Site id.")],
    body: SiteUpdate,
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
) -> SiteOut:
    principal.require(Permission.ASSETS_WRITE)
    return await service.replace_site(access, site_id, body)


@router.delete(
    "/sites/{site_id}",
    operation_id="deleteSite",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decommission (or purge) a site",
    description="Sets the site's status to `decommissioned`, which keeps it readable for the devices and "
    "events that refer to it. `purge=true` deletes it irreversibly.",
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: _WRITE_FORBIDDEN,
        status.HTTP_404_NOT_FOUND: _SITE_NOT_FOUND,
        status.HTTP_409_CONFLICT: _CONFLICT,
    },
    openapi_extra=requires(Permission.ASSETS_WRITE, purge=Permission.DATA_PURGE),
)
async def delete_site(
    site_id: Annotated[uuid.UUID, Path(description="Site id.")],
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
    purge: Annotated[bool, Query(description="Delete the site irreversibly.")] = False,
    version: Annotated[int | None, Query(ge=1, description="Only at this version.")] = None,
) -> None:
    principal.require(Permission.ASSETS_WRITE)
    if purge:
        principal.require(Permission.DATA_PURGE)
    await service.delete_site(access, site_id, purge=purge, version=version)


@router.get(
    "/devices/{device_id}/placement",
    operation_id="getDevicePlacement",
    response_model=DevicePlacementOut,
    summary="Read a device placement",
    description=PLACEMENT_GET_DESCRIPTION,
    responses={
        **_COMMON,
        status.HTTP_403_FORBIDDEN: other_tenant(_PLACEMENT),
        status.HTTP_404_NOT_FOUND: _DEVICE_NOT_FOUND,
    },
    openapi_extra=requires(Permission.MAP_READ),
)
async def get_device_placement(
    device_id: Annotated[uuid.UUID, Path(description="Device id.")],
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
    response: Response,
    at: Annotated[
        datetime | None,
        Query(description="Field of view in effect at this instant; default: now."),
    ] = None,
) -> DevicePlacementOut:
    principal.require(Permission.MAP_READ)
    response.headers["Cache-Control"] = "no-store"
    return await service.placement(access, device_id, at)


@router.put(
    "/devices/{device_id}/placement",
    operation_id="putDevicePlacement",
    response_model=DevicePlacementOut,
    summary="Register or move a device",
    description=PLACEMENT_PUT_DESCRIPTION,
    responses={
        **_COMMON,
        status.HTTP_201_CREATED: {"description": "The device was registered with this id."},
        status.HTTP_403_FORBIDDEN: _WRITE_FORBIDDEN,
        status.HTTP_409_CONFLICT: _CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _POSITION_INVALID,
    },
    openapi_extra=requires(Permission.ASSETS_WRITE),
)
async def put_device_placement(
    device_id: Annotated[uuid.UUID, Path(description="Device id (chosen by the client).")],
    body: DevicePlacementIn,
    principal: PrincipalDep,
    access: AccessDep,
    service: OperationalServiceDep,
    response: Response,
) -> DevicePlacementOut:
    principal.require(Permission.ASSETS_WRITE)
    placement, created = await service.put_placement(access, device_id, body)
    if created:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = f"/geo/v1/devices/{placement.id}/placement"
    return placement
