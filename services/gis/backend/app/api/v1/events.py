"""``GET /geo/v1/events``: event locations of one tenant, for a map view or a timeline.

This reads back what enrichment stored: where events were observed, and the geographic context computed
for them. It filters by time, by viewport, by event type, by the device that reported them, by a geofence
they were found in, and by administrative area.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.deps import PrincipalDep, SpatialQueryServiceDep, access_for
from app.api.v1.problems import other_tenant, problem, requires
from app.core.access import Permission
from app.schemas.spatial_query import EVENT_MAX_WINDOW_DAYS, EventCollectionOut, EventListQuery

router = APIRouter(tags=["events"])

DESCRIPTION = f"""
Event locations of one tenant as a GeoJSON `FeatureCollection`, newest first.

* **Time**: `from` and `to` bound the window on `observedAt`; `from` is inclusive, `to` exclusive. Default:
  the last 24 hours. The window may not exceed {EVENT_MAX_WINDOW_DAYS} days - event storage is partitioned
  by month, and a bounded window is what keeps a query on a few partitions.
* **Viewport**: `bbox=minLon,minLat,maxLon,maxLat` returns the events inside that box.
* **Type**: `eventType`, `eventSubtype`, `sourceType`, `deviceId`.
* **Geofence**: `geofenceId` returns the events whose geo-context recorded a hit on that geofence.
* **Administrative area**: `adminAreaId` or `adminAreaCode` returns the events the geo-context placed in
  that province, district, DS division or GN division (any level).
* **Paging**: order is `observedAt` descending, then `eventId`; pass `nextCursor` back as `cursor`.

Each feature carries the event's own attributes plus `admin` (the codes of the four administrative levels)
and `refDataRelease` from its geo-context, which is null for an event whose context was not computed.
The answer echoes the `window` it used. Every event query is recorded in the audit log.
"""

_EVENTS = "/geo/v1/events"

RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_403_FORBIDDEN: other_tenant(_EVENTS),
    status.HTTP_422_UNPROCESSABLE_CONTENT: problem(
        422,
        "time_window_too_large",
        "Time window is too large",
        f"The window is longer than {EVENT_MAX_WINDOW_DAYS} days (`time_window_too_large`), `to` is before "
        "`from`, `bbox` is malformed (`invalid_bbox`), or the cursor belongs to another query "
        "(`invalid_cursor`).",
        _EVENTS,
    ),
}


@router.get(
    "/events",
    operation_id="listEvents",
    response_model=EventCollectionOut,
    summary="Event locations in a window and area (GeoJSON)",
    description=DESCRIPTION,
    responses=RESPONSES,
    openapi_extra=requires(Permission.EVENTS_READ),
)
async def list_events(
    params: Annotated[EventListQuery, Query()],
    principal: PrincipalDep,
    service: SpatialQueryServiceDep,
    response: Response,
) -> EventCollectionOut:
    principal.require(Permission.EVENTS_READ)
    response.headers["Cache-Control"] = "no-store"
    return await service.events(params, access_for(principal, params.tenant_id))
