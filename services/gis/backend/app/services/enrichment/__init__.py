"""Geo-context enrichment engine (component C3).

* :mod:`.validation`  checks that need no database (time, coordinates, geometry)
* :mod:`.assembly`    pure, deterministic construction of the ``geo-context/1`` document
* :mod:`.service`     transactions, device resolution, storage and the single-statement lookup

The service is transport-neutral: the HTTP endpoint (``POST /geo/v1/enrich``) uses it today and an
event-stream consumer can use it unchanged.
"""

from app.services.enrichment.assembly import GeoContextLimits, build_admin_hierarchy, reference_point_wkb
from app.services.enrichment.service import (
    DeviceNotFoundError,
    EventNotFoundError,
    FieldOfViewNotFoundError,
    GeoContextService,
)
from app.services.enrichment.validation import MAX_CLOCK_SKEW, ValidatedEvent, validate_event
from app.services.releases import (
    ReferenceDataUnavailableError,
    ReleaseNotFoundError,
    ReleaseNotUsableError,
)

__all__ = [
    "MAX_CLOCK_SKEW",
    "DeviceNotFoundError",
    "EventNotFoundError",
    "FieldOfViewNotFoundError",
    "GeoContextLimits",
    "GeoContextService",
    "ReferenceDataUnavailableError",
    "ReleaseNotFoundError",
    "ReleaseNotUsableError",
    "ValidatedEvent",
    "build_admin_hierarchy",
    "reference_point_wkb",
    "validate_event",
]
