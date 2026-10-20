"""Geo-context enrichment: store where an event happened and derive its geographic context.

Flow for one event (plan §4.2 steps 2-3; no recipient lookup, no notifications):

1. validate the event without the database (time, coordinates, geometry validity)
2. in one transaction, with the event's tenant set for row-level security:
   a. resolve the device position and the field of view in effect (device events)
   b. store the location in ``geo.event_location`` (monthly partition; created on demand for recent
      months) and discard a context computed for an earlier location of the same event
   c. compute every part of the context in one indexed statement against a reference data release
   d. assemble the ``geo-context/1`` document (pure, deterministic) and store it with its hits
3. return the document

Entry points call :meth:`GeoContextService.enrich` with an :class:`~app.schemas.events.EventLocationIn`,
after they have checked that the caller acts for ``event.tenant_id``: the HTTP API from the tenant the
request acts for, an event-stream consumer from the stream's configuration. Enrichment is idempotent: an
event is keyed by tenant, event id and observation time, so a redelivered event replaces its earlier
result.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import Access
from app.core.errors import GisValidationError, NotFoundError, PermissionDeniedError
from app.core.tenancy import TenantId
from app.db.session import access_transaction, transaction
from app.repositories.audit import AuditRecord, AuditRepository
from app.repositories.events import (
    EventLocationRecord,
    EventPartitionMissingError,
    EventRepository,
    StoredEventLocation,
)
from app.repositories.spatial_lookup import ContextLookupQuery, SpatialLookupRepository
from app.schemas.events import EventLocationIn
from app.schemas.geo_context import GeoContext
from app.services.enrichment.assembly import (
    GeoContextLimits,
    assemble_geo_context,
    geo_context_record,
    reference_point_wkb,
)
from app.services.enrichment.validation import ValidatedEvent, validate_event
from app.services.releases import (
    ReferenceDataUnavailableError,
    ReleaseNotFoundError,
    ReleaseNotUsableError,
    require_usable_release,
)
from app.spatial.service_area import ServiceArea

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
T = TypeVar("T")

__all__ = [
    "DeviceNotFoundError",
    "EventNotFoundError",
    "FieldOfViewNotFoundError",
    "GeoContextService",
    "ReferenceDataUnavailableError",
    "ReleaseNotFoundError",
    "ReleaseNotUsableError",
]


class DeviceNotFoundError(NotFoundError):
    code = "device_not_found"
    title = "Device not found"


class FieldOfViewNotFoundError(NotFoundError):
    code = "field_of_view_not_found"
    title = "Field of view not found"


class EventNotFoundError(NotFoundError):
    code = "event_not_found"
    title = "Event not found"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GeoContextService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service_area: ServiceArea,
        limits: GeoContextLimits | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._service_area = service_area
        self._limits = limits or GeoContextLimits()
        self._clock = clock

    @property
    def limits(self) -> GeoContextLimits:
        return self._limits

    async def enrich(
        self, event: EventLocationIn, *, release_code: str | None = None, access: Access | None = None
    ) -> GeoContext:
        """Store the event location and its geo-context in one transaction and return the context.

        ``release_code`` pins a reference data release; by default the current release is used. With the
        caller's ``access`` (every API call), the call is recorded in the audit log in the same transaction:
        the answer names the tenant's geofences and devices near the event, so it is a read of operational
        data like any other.
        """
        started = time.perf_counter()
        validated = validate_event(event, service_area=self._service_area, now=self._clock())
        if access is not None and access.tenant != validated.tenant:
            # The API authorises the event's tenant first; this keeps the audit entry honest regardless.
            raise PermissionDeniedError(
                "the event's tenant is not the tenant this request acts for",
                extensions={"tenantId": validated.tenant.value},
            )

        async def store_and_compute(session: AsyncSession) -> GeoContext:
            location = await self._store_location(session, validated)
            context = await self._compute(session, location, release_code)
            if access is not None:
                await AuditRepository(session).record(_enrichment_record(location, context))
            return context

        context = await self._with_event_partition(validated, store_and_compute, access)
        logger.info(
            "geo-context computed",
            extra={
                "tenant_id": context.tenant_id,
                "event_id": context.event_id,
                "ref_data_release": context.ref_data_release,
                "geometry_kind": context.geometry_kind,
                "zone_hits": len(context.inside_zones),
                "geofence_hits": len(context.geofence_hits),
                "nearby_devices": len(context.nearest_devices),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return context

    async def record_location(self, event: EventLocationIn) -> StoredEventLocation:
        """Store (or replace) the event location only; compute its context later with :meth:`recompute`."""
        validated = validate_event(event, service_area=self._service_area, now=self._clock())

        async def store(session: AsyncSession) -> StoredEventLocation:
            return await self._store_location(session, validated)

        return await self._with_event_partition(validated, store)

    async def recompute(
        self, tenant: TenantId, event_id: str, observed_at: datetime, *, release_code: str | None = None
    ) -> GeoContext:
        """Recompute the context of a stored event, e.g. against a new reference data release."""
        async with transaction(self._session_factory, tenant) as session:
            location = await EventRepository(session).get_location(event_id, observed_at)
            if location is None:
                raise EventNotFoundError(
                    f"event {event_id} observed at {observed_at.isoformat()} not found",
                    extensions={"eventId": event_id, "observedAt": observed_at.isoformat()},
                )
            return await self._compute(session, location, release_code)

    async def get(self, tenant: TenantId, event_id: str, observed_at: datetime) -> GeoContext | None:
        async with transaction(self._session_factory, tenant) as session:
            document = await EventRepository(session).get_geo_context_document(event_id, observed_at)
        return None if document is None else GeoContext.model_validate(document)

    async def _with_event_partition(
        self,
        validated: ValidatedEvent,
        work: Callable[[AsyncSession], Awaitable[T]],
        access: Access | None = None,
    ) -> T:
        """Run ``work`` in a tenant transaction; if the event's month has no partition yet, create it
        (recent months only) and run ``work`` once more in a new transaction."""
        for attempt in (1, 2):
            try:
                if access is None:
                    async with transaction(self._session_factory, validated.tenant) as session:
                        return await work(session)
                async with access_transaction(self._session_factory, access) as session:
                    return await work(session)
            except EventPartitionMissingError:
                if attempt == 2:
                    raise
                await self._prepare_partition(validated.event.observed_at)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _prepare_partition(self, observed_at: datetime) -> None:
        # Separate, short transaction: creating a partition locks the partitioned table briefly.
        async with transaction(self._session_factory) as session:
            try:
                await EventRepository(session).ensure_partition(observed_at)
            except DBAPIError as exc:
                if "outside the on-demand window" in str(exc):
                    raise GisValidationError(
                        "observedAt is too old to be stored without preparation; events older than 13 months "
                        "need their month prepared by an operator",
                        extensions={"observedAt": observed_at.isoformat()},
                    ) from exc
                raise

    async def _store_location(self, session: AsyncSession, validated: ValidatedEvent) -> StoredEventLocation:
        event = validated.event
        geometry_wkb = None if validated.geometry is None else validated.geometry.wkb()
        fov_id = None
        fov_wkb = None
        if event.device_id is not None:
            device = await SpatialLookupRepository(session).event_device(
                event.device_id, event.observed_at, event.field_of_view_id
            )
            if device is None:
                raise DeviceNotFoundError(
                    f"device {event.device_id} not found", extensions={"deviceId": str(event.device_id)}
                )
            if device.tenant_id != validated.tenant.value:
                # Shared devices are visible, but an event is always reported by the device's owner.
                raise GisValidationError(
                    "events can only reference devices of the reporting tenant",
                    extensions={"deviceId": str(event.device_id)},
                )
            if event.field_of_view_id is not None and device.field_of_view_id is None:
                raise FieldOfViewNotFoundError(
                    "field of view not found for this device at the observation time",
                    extensions={"fieldOfViewId": str(event.field_of_view_id)},
                )
            if geometry_wkb is None:
                geometry_wkb = device.wkb
            fov_id, fov_wkb = device.field_of_view_id, device.field_of_view_wkb
        if geometry_wkb is None:  # guarded by EventLocationIn; kept for type narrowing
            raise GisValidationError("event has no location")

        tenant_id, geometry_kind = await EventRepository(session).upsert_location(
            EventLocationRecord(
                event_id=event.event_id,
                observed_at=event.observed_at,
                event_type=event.event_type,
                event_subtype=event.event_subtype,
                source_type=event.source_type,
                device_id=event.device_id,
                source_ref=event.source_ref,
                location_source=event.location_source,
                geometry_wkb=geometry_wkb,
                location_accuracy_m=event.location_accuracy_m,
                field_of_view_id=fov_id,
                field_of_view_wkb=fov_wkb,
                attributes=event.metadata,
            )
        )
        return StoredEventLocation(
            tenant_id=tenant_id,
            event_id=event.event_id,
            observed_at=event.observed_at,
            event_type=event.event_type,
            location_source=event.location_source,
            geometry_kind=geometry_kind,
            geometry_wkb=geometry_wkb,
            device_id=event.device_id,
            field_of_view_id=fov_id,
            location_accuracy_m=event.location_accuracy_m,
        )

    async def _compute(
        self, session: AsyncSession, location: StoredEventLocation, release_code: str | None
    ) -> GeoContext:
        limits = self._limits
        lookup = await SpatialLookupRepository(session).lookup_context(
            ContextLookupQuery(
                geometry_wkb=location.geometry_wkb,
                reference_point_wkb=reference_point_wkb(location.geometry_wkb),
                observed_at=location.observed_at,
                release_code=release_code,
                settlement_radius_m=limits.settlement_radius_m,
                road_radius_m=limits.road_radius_m,
                device_radius_m=limits.device_radius_m,
                device_limit=limits.device_limit,
                source_device_id=location.device_id,
            )
        )
        release = require_usable_release(lookup.release, release_code)
        context = assemble_geo_context(location, lookup, release, limits, computed_at=self._clock())
        await EventRepository(session).store_geo_context(geo_context_record(context, release))
        return context


def _enrichment_record(location: StoredEventLocation, context: GeoContext) -> AuditRecord:
    """What an enrichment call revealed: how many of the tenant's geofences and devices, and roughly where."""
    hits, devices = len(context.geofence_hits), len(context.nearest_devices)
    return AuditRecord(
        category="sensitive_query",
        operation="events.enrich",
        target="geo.event_location",
        object_id=location.event_id,
        geometry_wkb=location.geometry_wkb,
        parameters={
            "observedAt": location.observed_at,
            "eventType": location.event_type,
            "refDataRelease": context.ref_data_release,
            "geofenceHits": hits,
            "nearbyDevices": devices,
            "insideZones": len(context.inside_zones),
        },
        result_count=hits + devices,
    )
