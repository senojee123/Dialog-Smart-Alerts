"""Event validation that needs no database.

Runs before a transaction is opened, so a malformed event never touches the database. The checks the
database repeats (validity, service-area envelope, clock skew) are the backstop, not the first line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.core.errors import GisValidationError
from app.core.tenancy import TenantId
from app.schemas.events import EventLocationIn
from app.spatial.geometry import ValidatedGeometry, parse_geojson_geometry
from app.spatial.service_area import ServiceArea

# Same tolerance as ck_event_location_observed_at_not_future (migration 20260915_0005).
MAX_CLOCK_SKEW: Final = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class ValidatedEvent:
    """An event whose tenant, time and geometry are acceptable.

    ``geometry`` is None when the event uses the position of its device (``locationSource`` device
    without ``location``); the service resolves it.
    """

    event: EventLocationIn
    tenant: TenantId
    geometry: ValidatedGeometry | None


def validate_event(event: EventLocationIn, *, service_area: ServiceArea, now: datetime) -> ValidatedEvent:
    """Check what the schema cannot: the observation time and the geometry (coordinates, validity).

    Raises :class:`~app.core.errors.CoordinateError` for positions outside WGS84 or the service area
    (with ``likelySwapped`` when ``[lat, lon]`` was sent), :class:`~app.core.errors.InvalidGeometryError`
    for invalid geometries (with the reason and location) and :class:`GisValidationError` otherwise.
    """
    if event.observed_at > now + MAX_CLOCK_SKEW:
        raise GisValidationError(
            "observedAt lies in the future",
            extensions={
                "observedAt": event.observed_at.isoformat(),
                "maxClockSkewS": int(MAX_CLOCK_SKEW.total_seconds()),
            },
        )
    geometry = (
        None
        if event.location is None
        else parse_geojson_geometry(event.location.as_mapping(), area=service_area)
    )
    return ValidatedEvent(event=event, tenant=TenantId(event.tenant_id), geometry=geometry)
