"""``POST /geo/v1/enrich``: compute and store the geo-context of one event (plan §7, synchronous path).

HTTP concerns only: the tenant the request acts for, request parsing, response shaping. Validation,
the spatial lookups and storage live in :mod:`app.services.enrichment`, which an event-stream consumer
can call in the same way.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Response, status

from app.api.deps import GeoContextServiceDep, PrincipalDep, access_for
from app.api.v1.enrichment_examples import REQUEST_EXAMPLES, RESPONSE_EXAMPLE
from app.api.v1.problems import requires
from app.core.access import Permission
from app.schemas.events import EventLocationIn
from app.schemas.geo_context import GeoContext
from app.schemas.problem import PROBLEM_CONTENT_TYPE
from app.schemas.reference_data import RELEASE_CODE_PATTERN

router = APIRouter(tags=["geo-context"])

DESCRIPTION = """
Stores the event location and returns its **geo-context** (`geo-context/1`): admin hierarchy
(province, district, DS and GN division), nearest settlement and road with distances, protected areas
and risk zones the event lies in, geofence hits visible to the tenant, nearby devices, and the reference
data release used.

* **Input**: GeoJSON geometry in WGS84, `[longitude, latitude]` (Point, LineString, Polygon and the Multi
  forms). Positions outside Sri Lanka's service area are rejected; when swapped axes would be inside it,
  the problem says `likelySwapped`. Invalid geometries are rejected with the reason and location.
  With `locationSource` `device` and no `location`, the registered device position is used.
* **Distances** are metres in EPSG:5235 (SLD99), rounded to 0.01 m. Search radii are inclusive: a
  feature exactly at the radius is included. Containment is boundary-inclusive.
* **Determinism**: the same event, release and tenant data give the same document except `computedAt`.
* **Idempotency**: an event is identified by `tenantId`, `eventId` and `observedAt`. Sending it again
  replaces the stored location and context.
* **Tenant**: `tenantId` must be the tenant the request acts for (the `X-GIS-Tenant-Id` header, else the
  platform's organisation). The GIS checks no credentials; the main platform calls it.
* **Audit**: every call is recorded in the audit log (`events.enrich`): the answer names the tenant's
  geofences and devices near the event, so it is a read of operational data.

The response contains spatial facts only. The GIS service does not raise alerts or select recipients.
"""


def _problem(description: str, example_code: str, example_title: str, status_code: int) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            PROBLEM_CONTENT_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProblemDetail"},
                "example": {
                    "type": f"urn:gis-core-service:problem:{example_code}",
                    "title": example_title,
                    "status": status_code,
                    "detail": description,
                    "instance": "/geo/v1/enrich",
                    "requestId": "5f0c6f0f2f5c4b1f9a55c6f1d2a7e3b4",
                },
            }
        },
    }


RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_200_OK: {"content": {"application/json": {"example": RESPONSE_EXAMPLE}}},
    status.HTTP_403_FORBIDDEN: _problem(
        "`tenantId` is not the tenant the request acts for (`forbidden`), or the tenant is not registered "
        "with the GIS service (`tenant_not_registered`).",
        "forbidden",
        "Not permitted",
        403,
    ),
    status.HTTP_404_NOT_FOUND: _problem(
        "`deviceId`, `fieldOfViewId` or the requested `refDataRelease` does not exist for this tenant "
        "(`device_not_found`, `field_of_view_not_found`, `release_not_found`).",
        "device_not_found",
        "Device not found",
        404,
    ),
    status.HTTP_413_CONTENT_TOO_LARGE: _problem(
        "The request body exceeds `GIS_MAX_REQUEST_BODY_BYTES` (`payload_too_large`).",
        "payload_too_large",
        "Request body too large",
        413,
    ),
    status.HTTP_422_UNPROCESSABLE_CONTENT: _problem(
        "The event is invalid: schema errors (`request_validation_error`, with `errors`), coordinates "
        "outside WGS84 or the service area (`invalid_coordinate`, with `path`, `position` and "
        "`likelySwapped`), invalid geometry (`invalid_geometry`, with `reason`), `observedAt` too far in the "
        "future or too old (`validation_error`), a draft release (`release_not_usable`), or a device of "
        "another tenant.",
        "invalid_coordinate",
        "Coordinate is not acceptable",
        422,
    ),
    status.HTTP_503_SERVICE_UNAVAILABLE: _problem(
        "No current reference data release (`reference_data_unavailable`), or event storage not prepared "
        "(`event_partition_missing`).",
        "reference_data_unavailable",
        "No reference data release is available",
        503,
    ),
}


@router.post(
    "/enrich",
    operation_id="enrichEvent",
    response_model=GeoContext,
    response_model_by_alias=True,
    summary="Compute the geo-context of an event",
    description=DESCRIPTION,
    responses=RESPONSES,
    openapi_extra=requires(Permission.EVENTS_ENRICH),
)
async def enrich_event(
    event: Annotated[EventLocationIn, Body(openapi_examples=REQUEST_EXAMPLES)],
    principal: PrincipalDep,
    service: GeoContextServiceDep,
    response: Response,
    ref_data_release: Annotated[
        str | None,
        Query(
            alias="refDataRelease",
            pattern=RELEASE_CODE_PATTERN,
            description="Compute against this published release instead of the current one "
            "(e.g. to reproduce an earlier result).",
            examples=["ref-2026.09-lka-open"],
        ),
    ] = None,
) -> GeoContext:
    principal.require(Permission.EVENTS_ENRICH)
    access = access_for(principal, event.tenant_id)
    context = await service.enrich(event, release_code=ref_data_release, access=access)
    response.headers["Cache-Control"] = "no-store"
    return context
