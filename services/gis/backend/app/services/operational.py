"""Managing the operational map: geofences, sites and where devices are placed.

The service owns the rules that surround the data:

* **tenant ownership.** Every object belongs to the tenant that created it. Reading may include objects
  another tenant shared, changing and deleting never does - the attempt is refused with 403 rather than
  silently doing nothing, so a caller can tell "not yours" from "not there".
* **versions.** A change states the version it is based on; if the object moved on in the meantime the
  request is refused with 409 instead of overwriting someone else's edit.
* **real geometry.** A geofence stores the geometry its author defined - a polygon, a circle's centre and
  radius, a corridor's centre line and half-width - validated as WGS84 inside the service area and
  geometrically valid. The database derives the search polygons from it.
* **retiring, not losing.** Deleting a geofence archives it (and a site is decommissioned), which keeps
  stored geo-context hits meaningful; ``purge`` really removes it for a mistake that should never have
  existed.

Geofences are areas on a map. That an event lies inside one is a spatial fact, and the only thing this
service produces; who hears about it is not part of the GIS service (ADR-0012).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import Access
from app.core.errors import (
    GisError,
    GisValidationError,
    InvalidGeometryError,
    NotFoundError,
    UnsupportedFilterError,
)
from app.core.paging import build_page, cursor_of, fetch_limit, query_fingerprint
from app.core.tenancy import TenantId
from app.db.session import access_transaction
from app.repositories.audit import AuditRecord, AuditRepository
from app.repositories.events import UnknownTenantError
from app.repositories.operational import (
    DEVICE_EXTERNAL_ID_UNIQUE,
    DEVICE_ID_PRIMARY_KEY,
    DEVICE_SITE_FOREIGN_KEY,
    FIELD_OF_VIEW_OVERLAP,
    GEOFENCE_EXTERNAL_ID_UNIQUE,
    SITE_EXTERNAL_ID_UNIQUE,
    TENANT_FOREIGN_KEYS,
    DeviceRow,
    DeviceValues,
    FieldOfViewValues,
    GeofenceRow,
    GeofenceValues,
    ListFilters,
    OperationalRepository,
    OwnershipValues,
    SiteRow,
    SiteValues,
)
from app.repositories.pg_errors import (
    EXCLUSION_VIOLATION,
    FOREIGN_KEY_VIOLATION,
    INVALID_PARAMETER_VALUE,
    UNIQUE_VIOLATION,
    server_message,
    sqlstate,
    violated_constraint,
)
from app.schemas.geojson import GeoJsonGeometry
from app.schemas.operational import (
    DevicePlacementIn,
    DevicePlacementOut,
    FieldOfViewIn,
    FieldOfViewOut,
    GeofenceDefinition,
    GeofenceIn,
    GeofenceListOut,
    GeofenceOut,
    GeofenceUpdate,
    OperationalListQuery,
    Ownership,
    Period,
    SiteIn,
    SiteListOut,
    SiteOut,
    SiteUpdate,
)
from app.services import audit_policy
from app.spatial.geometry import LINE_TYPES, POINT_TYPES, POLYGON_TYPES, parse_geojson_geometry
from app.spatial.layers import (
    GEOFENCE_KINDS,
    GEOFENCE_STATUSES,
    SITE_STATUSES,
    SITE_TYPES,
)
from app.spatial.service_area import ServiceArea
from app.spatial.validation import parse_bbox

Clock = Callable[[], datetime]

DEFINITION_TYPES: Final = {"polygon": POLYGON_TYPES, "circle": POINT_TYPES, "corridor": LINE_TYPES}
GEOFENCE_TABLE: Final = "ops.geofence"
SITE_TABLE: Final = "ops.site"
DEVICE_TABLE: Final = "ops.device"


class GeofenceNotFoundError(NotFoundError):
    code = "geofence_not_found"
    title = "Geofence not found"


class SiteNotFoundError(NotFoundError):
    code = "site_not_found"
    title = "Site not found"


class DeviceNotFoundError(NotFoundError):
    code = "device_not_found"
    title = "Device not found"


class NotOwnerError(GisError):
    """Only the owning tenant may change or delete an object, even when it is shared for reading."""

    status_code = 403
    code = "not_owner"
    title = "Object belongs to another tenant"


class ConflictError(GisError):
    status_code = 409
    code = "conflict"
    title = "Request conflicts with the stored object"


class VersionConflictError(ConflictError):
    code = "version_conflict"
    title = "Object has changed since it was read"


class ExternalIdInUseError(ConflictError):
    code = "external_id_in_use"
    title = "External id is already used by another object"


class IdentifierInUseError(ConflictError):
    """The identifier the caller chose is taken by an object it cannot see."""

    code = "identifier_in_use"
    title = "Identifier is already in use"


class FieldOfViewOverlapError(ConflictError):
    code = "field_of_view_overlap"
    title = "Field of view overlaps an existing period"


class UnknownSiteError(GisValidationError):
    code = "unknown_site"
    title = "Site does not exist for this tenant"


def _utc_now() -> datetime:
    return datetime.now(UTC)


_UNIQUE_EXTERNAL_IDS: Final = frozenset(
    {GEOFENCE_EXTERNAL_ID_UNIQUE, SITE_EXTERNAL_ID_UNIQUE, DEVICE_EXTERNAL_ID_UNIQUE}
)


def _translated(error: DBAPIError) -> GisError | None:
    """The problem a PostgreSQL error stands for, or None if it is not one this service expects."""
    state, constraint = sqlstate(error), violated_constraint(error)
    if state == INVALID_PARAMETER_VALUE:
        # Geometry a trigger refused (invalid definition, outside the service area, not derivable).
        return InvalidGeometryError(server_message(error))
    if state == UNIQUE_VIOLATION and constraint == DEVICE_ID_PRIMARY_KEY:
        return IdentifierInUseError(
            "another device already has this id; choose a new one",
            extensions={"constraint": constraint},
        )
    if state == UNIQUE_VIOLATION and constraint in _UNIQUE_EXTERNAL_IDS:
        return ExternalIdInUseError(
            "externalId is already used by another object of this tenant",
            extensions={"constraint": constraint},
        )
    if state == FOREIGN_KEY_VIOLATION and constraint == DEVICE_SITE_FOREIGN_KEY:
        return UnknownSiteError("siteId does not name a site of this tenant")
    if state == FOREIGN_KEY_VIOLATION and constraint in TENANT_FOREIGN_KEYS:
        # The request acts for the tenant, but the GIS service does not know it yet (as for events).
        return UnknownTenantError(
            "this tenant is not registered with the GIS service", extensions={"constraint": constraint}
        )
    if state == EXCLUSION_VIOLATION and constraint == FIELD_OF_VIEW_OVERLAP:
        return FieldOfViewOverlapError(
            "the new field of view overlaps a period that is already recorded for this device"
        )
    if state in (INVALID_PARAMETER_VALUE, "23514") and constraint is not None:
        return GisValidationError(f"the object violates {constraint}", extensions={"constraint": constraint})
    return None


@asynccontextmanager
async def _database_problems() -> AsyncIterator[None]:
    """Turn the PostgreSQL errors this service expects into problem details.

    The transaction this runs inside is rolled back by its own context manager; translating the error
    first only changes what the caller is told.
    """
    try:
        yield
    except DBAPIError as error:
        problem = _translated(error)
        if problem is None:
            raise
        raise problem from error


class OperationalService:
    """Everything a tenant can change on its own part of the map."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service_area: ServiceArea,
        clock: Clock = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._service_area = service_area
        self._clock = clock

    # --- geofences --------------------------------------------------------------------------------

    async def create_geofence(self, access: Access, body: GeofenceIn) -> GeofenceOut:
        values = self._geofence_values(body)
        self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session, _database_problems():
            row = await OperationalRepository(session).create_geofence(values, access.actor.label)
        return _geofence_out(row)

    async def geofence(self, access: Access, geofence_id: uuid.UUID) -> GeofenceOut:
        self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session:
            row = await OperationalRepository(session).geofence(geofence_id)
            await AuditRepository(session).record(
                audit_policy.operational_read(
                    "geofence.read", GEOFENCE_TABLE, int(row is not None), object_id=str(geofence_id)
                )
            )
        if row is None:
            raise _not_found("geofence", geofence_id)
        return _for_reader(_geofence_out(row), access)

    async def geofences(self, access: Access, params: OperationalListQuery) -> GeofenceListOut:
        tenant = self._require_tenant(access)
        filters, fingerprint, cursor = self._list_filters("geofences", tenant, params)
        async with access_transaction(self._session_factory, access) as session:
            rows = await OperationalRepository(session).geofences(filters)
            page = build_page(rows, limit=params.limit, fingerprint=fingerprint, key_of=_by_id)
            await AuditRepository(session).record(
                self._list_record("geofences.list", GEOFENCE_TABLE, filters, page.count, cursor is not None)
            )
        return GeofenceListOut(
            items=[_for_reader(_geofence_out(row), access) for row in page.items],
            count=page.count,
            next_cursor=page.next_cursor,
        )

    async def replace_geofence(
        self, access: Access, geofence_id: uuid.UUID, body: GeofenceUpdate
    ) -> GeofenceOut:
        values = self._geofence_values(body)
        tenant = self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session, _database_problems():
            repository = OperationalRepository(session)
            await self._require_own("geofence", repository, tenant, geofence_id, body.version)
            row = await repository.update_geofence(
                geofence_id, values, version=body.version, actor=access.actor.label
            )
        if row is None:  # pragma: no cover - the state check above has already reported why
            raise _version_conflict("geofence", geofence_id, body.version)
        return _geofence_out(row)

    async def delete_geofence(
        self,
        access: Access,
        geofence_id: uuid.UUID,
        *,
        purge: bool,
        version: int | None,
    ) -> None:
        """Archive the geofence, or remove it entirely with ``purge``.

        Archiving keeps the row: geo-context hits computed earlier name this geofence and its version, and
        an operator looking at them should still find it.
        """
        tenant = self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session, _database_problems():
            repository = OperationalRepository(session)
            await self._require_own("geofence", repository, tenant, geofence_id, version)
            done = (
                await repository.delete_geofence(geofence_id)
                if purge
                else await repository.archive_geofence(geofence_id, version=version, actor=access.actor.label)
            )
        if not done:  # pragma: no cover - the state check above has already reported why
            raise _not_found("geofence", geofence_id)

    # --- sites ------------------------------------------------------------------------------------

    async def create_site(self, access: Access, body: SiteIn) -> SiteOut:
        values = self._site_values(body)
        self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session, _database_problems():
            row = await OperationalRepository(session).create_site(values, access.actor.label)
        return _site_out(row)

    async def site(self, access: Access, site_id: uuid.UUID) -> SiteOut:
        self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session:
            row = await OperationalRepository(session).site(site_id)
            await AuditRepository(session).record(
                audit_policy.operational_read(
                    "site.read", SITE_TABLE, int(row is not None), object_id=str(site_id)
                )
            )
        if row is None:
            raise _not_found("site", site_id)
        return _for_reader(_site_out(row), access)

    async def sites(self, access: Access, params: OperationalListQuery) -> SiteListOut:
        tenant = self._require_tenant(access)
        filters, fingerprint, cursor = self._list_filters("sites", tenant, params)
        async with access_transaction(self._session_factory, access) as session:
            rows = await OperationalRepository(session).sites(filters)
            page = build_page(rows, limit=params.limit, fingerprint=fingerprint, key_of=_by_id)
            await AuditRepository(session).record(
                self._list_record("sites.list", SITE_TABLE, filters, page.count, cursor is not None)
            )
        return SiteListOut(
            items=[_for_reader(_site_out(row), access) for row in page.items],
            count=page.count,
            next_cursor=page.next_cursor,
        )

    async def replace_site(self, access: Access, site_id: uuid.UUID, body: SiteUpdate) -> SiteOut:
        values = self._site_values(body)
        tenant = self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session, _database_problems():
            repository = OperationalRepository(session)
            await self._require_own("site", repository, tenant, site_id, body.version)
            row = await repository.update_site(
                site_id, values, version=body.version, actor=access.actor.label
            )
        if row is None:  # pragma: no cover - the state check above has already reported why
            raise _version_conflict("site", site_id, body.version)
        return _site_out(row)

    async def delete_site(
        self, access: Access, site_id: uuid.UUID, *, purge: bool, version: int | None
    ) -> None:
        tenant = self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session, _database_problems():
            repository = OperationalRepository(session)
            await self._require_own("site", repository, tenant, site_id, version)
            done = (
                await repository.delete_site(site_id)
                if purge
                else await repository.decommission_site(site_id, version=version, actor=access.actor.label)
            )
        if not done:  # pragma: no cover - the state check above has already reported why
            raise _not_found("site", site_id)

    # --- device placement -------------------------------------------------------------------------

    async def placement(
        self, access: Access, device_id: uuid.UUID, at: datetime | None = None
    ) -> DevicePlacementOut:
        self._require_tenant(access)
        async with access_transaction(self._session_factory, access) as session:
            row = await OperationalRepository(session).device(device_id, at)
            await AuditRepository(session).record(
                audit_policy.operational_read(
                    "device_placement.read",
                    DEVICE_TABLE,
                    int(row is not None),
                    object_id=str(device_id),
                    at=at,
                )
            )
        if row is None:
            raise _not_found("device", device_id)
        return _for_reader(_placement_out(row), access)

    async def put_placement(
        self, access: Access, device_id: uuid.UUID, body: DevicePlacementIn
    ) -> tuple[DevicePlacementOut, bool]:
        """Register or move a device. Returns the placement and whether the device was created."""
        values = self._device_values(body)
        field_of_view = None if body.field_of_view is None else self._field_of_view_values(body.field_of_view)
        tenant = self._require_tenant(access)
        actor = access.actor.label
        async with access_transaction(self._session_factory, access) as session, _database_problems():
            repository = OperationalRepository(session)
            state = await repository.state("device", device_id)
            created = state is None
            if state is None:
                if body.version is not None:
                    raise VersionConflictError(
                        f"device {device_id} does not exist yet, so there is no version to base a change on",
                        extensions={"deviceId": str(device_id), "version": body.version},
                    )
                await repository.create_device(device_id, values, actor)
            else:
                if state.tenant_id != tenant.value:
                    raise _not_owner("device", device_id, state.tenant_id)
                if body.version is None:
                    raise VersionConflictError(
                        f"device {device_id} already exists; send the version you read to change it",
                        extensions={"deviceId": str(device_id), "currentVersion": state.version},
                    )
                if state.version != body.version:
                    raise _version_conflict("device", device_id, body.version, state.version)
                await repository.update_device(device_id, values, version=body.version, actor=actor)
            if field_of_view is not None:
                await repository.replace_field_of_view(device_id, field_of_view, actor)
            row = await repository.device(device_id)
        if row is None:  # pragma: no cover - it was just written in the same transaction
            raise _not_found("device", device_id)
        return _placement_out(row), created

    # --- helpers ----------------------------------------------------------------------------------

    @staticmethod
    def _require_tenant(access: Access) -> TenantId:
        return access.required_tenant("geofences, sites and devices belong to a tenant; pass tenantId")

    @staticmethod
    def _list_record(
        operation: str, target: str, filters: ListFilters, count: int, continued: bool
    ) -> AuditRecord:
        return audit_policy.operational_read(
            operation,
            target,
            count,
            bbox=filters.bbox,
            status=filters.status,
            kind=filters.kind,
            siteType=filters.site_type,
            nameContains=filters.name_contains,
            at=filters.at,
            ownedOnly=filters.owned_only or None,
            limit=filters.limit - 1,
            continued=continued or None,
        )

    async def _require_own(
        self,
        table: str,
        repository: OperationalRepository,
        tenant: TenantId,
        object_id: uuid.UUID,
        version: int | None,
    ) -> None:
        """Refuse early, and with the right reason: not there, not yours, or changed since you read it."""
        state = await repository.state(table, object_id)
        if state is None:
            raise _not_found(table, object_id)
        if state.tenant_id != tenant.value:
            raise _not_owner(table, object_id, state.tenant_id)
        if version is not None and state.version != version:
            raise _version_conflict(table, object_id, version, state.version)

    def _list_filters(
        self, what: str, tenant: TenantId, params: OperationalListQuery
    ) -> tuple[ListFilters, str, Any]:
        _check_list_filters(what, params)
        bbox = None if params.bbox is None else parse_bbox(params.bbox, self._service_area)
        fingerprint = query_fingerprint(
            what,
            tenant.value,
            params.status,
            params.kind,
            params.site_type,
            params.name_contains,
            bbox,
            params.at,
            params.owned_only,
        )
        cursor = cursor_of(params.cursor, fingerprint=fingerprint)
        filters = ListFilters(
            limit=fetch_limit(params.limit),
            status=params.status,
            kind=params.kind,
            site_type=params.site_type,
            name_contains=params.name_contains,
            bbox=bbox,
            at=params.at,
            owned_only=params.owned_only,
            after_id=None if cursor is None else cursor.identifier("id"),
        )
        return filters, fingerprint, cursor

    def _geofence_values(self, body: GeofenceIn) -> GeofenceValues:
        definition = body.definition
        geometry = parse_geojson_geometry(
            definition.geometry.as_mapping(),
            area=self._service_area,
            allowed_types=DEFINITION_TYPES[definition.kind],
        )
        return GeofenceValues(
            name=body.name,
            description=body.description,
            external_id=body.external_id,
            geofence_kind=definition.kind,
            definition_wkb=geometry.wkb(),
            radius_m=definition.radius_m,
            status=body.status,
            effective_from=body.effective_during.time_from,
            effective_to=body.effective_during.time_to,
            ownership=_ownership(body),
            attributes=body.attributes,
        )

    def _site_values(self, body: SiteIn) -> SiteValues:
        position = parse_geojson_geometry(
            body.position.as_mapping(), area=self._service_area, allowed_types=POINT_TYPES
        )
        return SiteValues(
            name=body.name,
            external_id=body.external_id,
            site_type=body.site_type,
            status=body.status,
            position_wkb=position.wkb(),
            position_source=body.position_source,
            position_accuracy_m=body.position_accuracy_m,
            ownership=_ownership(body),
            attributes=body.attributes,
        )

    def _device_values(self, body: DevicePlacementIn) -> DeviceValues:
        position = parse_geojson_geometry(
            body.position.as_mapping(), area=self._service_area, allowed_types=POINT_TYPES
        )
        return DeviceValues(
            name=body.name,
            device_type=body.device_type,
            external_id=body.external_id,
            status=body.status,
            site_id=body.site_id,
            position_wkb=position.wkb(),
            position_source=body.position_source,
            position_accuracy_m=body.position_accuracy_m,
            mounting_height_m=body.mounting_height_m,
            installed_at=body.installed_at,
            decommissioned_at=body.decommissioned_at,
            ownership=_ownership(body),
            attributes=body.attributes,
        )

    def _field_of_view_values(self, body: FieldOfViewIn) -> FieldOfViewValues:
        geometry = (
            None
            if body.geometry is None
            else parse_geojson_geometry(
                body.geometry.as_mapping(), area=self._service_area, allowed_types=POLYGON_TYPES
            )
        )
        return FieldOfViewValues(
            geometry_method=body.method,
            bearing_deg=body.bearing_deg,
            fov_deg=body.fov_deg,
            range_m=body.range_m,
            geometry_wkb=None if geometry is None else geometry.wkb(),
        )


_NOT_FOUND: Final[dict[str, type[NotFoundError]]] = {
    "geofence": GeofenceNotFoundError,
    "site": SiteNotFoundError,
    "device": DeviceNotFoundError,
}


def _check_value(name: str, value: str | None, allowed: tuple[str, ...]) -> None:
    if value is not None and value not in allowed:
        raise UnsupportedFilterError(
            f"{name}={value!r} is not one of the values this collection has",
            extensions={"filter": name, "allowedValues": list(allowed)},
        )


def _reject(name: str, value: object, what: str) -> None:
    if value is not None:
        raise UnsupportedFilterError(
            f"{name} does not apply to {what}", extensions={"filter": name, "collection": what}
        )


def _check_list_filters(what: str, params: OperationalListQuery) -> None:
    """Only the filters a collection has, with the values it knows."""
    if what == "geofences":
        _reject("siteType", params.site_type, what)
        _check_value("status", params.status, GEOFENCE_STATUSES)
        _check_value("kind", params.kind, GEOFENCE_KINDS)
        return
    _reject("kind", params.kind, what)
    _reject("at", params.at, what)
    _check_value("status", params.status, SITE_STATUSES)
    _check_value("siteType", params.site_type, SITE_TYPES)


def _for_reader[O: (GeofenceOut, SiteOut, DevicePlacementOut)](out: O, access: Access) -> O:
    """An object as a tenant that does not own it sees it: without the owner's user and client ids.

    Sharing an object shares where it is and what it is, not who in the owning organisation edited it.
    """
    if access.tenant is not None and out.tenant_id == access.tenant.value:
        return out
    return out.model_copy(update={"created_by": None, "updated_by": None})


def _not_found(what: str, object_id: uuid.UUID) -> NotFoundError:
    return _NOT_FOUND[what](
        f"no {what} {object_id} visible to this tenant", extensions={"id": str(object_id)}
    )


def _not_owner(what: str, object_id: uuid.UUID, owner: str) -> NotOwnerError:
    return NotOwnerError(
        f"this {what} belongs to another tenant and is shared for reading only",
        extensions={"id": str(object_id), "ownerTenantId": owner},
    )


def _version_conflict(
    what: str, object_id: uuid.UUID, version: int, current: int | None = None
) -> VersionConflictError:
    extensions: dict[str, Any] = {"id": str(object_id), "version": version}
    if current is not None:
        extensions["currentVersion"] = current
    return VersionConflictError(
        f"the {what} has changed since version {version}; read it again and retry", extensions=extensions
    )


def _ownership(body: Ownership) -> OwnershipValues:
    return OwnershipValues(
        sharing_policy=body.sharing_policy, shared_with_tenants=list(body.shared_with_tenants)
    )


def _by_id(row: GeofenceRow | SiteRow) -> dict[str, Any]:
    return {"id": str(row.id)}


def _period(time_from: datetime | None, time_to: datetime | None) -> Period:
    return Period(time_from=time_from, time_to=time_to)


def _geofence_out(row: GeofenceRow) -> GeofenceOut:
    return GeofenceOut(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        description=row.description,
        external_id=row.external_id,
        definition=GeofenceDefinition.model_validate(
            {"kind": row.geofence_kind, "geometry": row.definition, "radiusM": row.radius_m}
        ),
        area_m2=row.area_m2,
        status=row.status,
        effective_during=_period(row.effective_from, row.effective_to),
        sharing_policy=row.sharing_policy,
        shared_with_tenants=list(row.shared_with_tenants),
        attributes=row.attributes,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
        updated_by=row.updated_by,
    )


def _site_out(row: SiteRow) -> SiteOut:
    return SiteOut(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        external_id=row.external_id,
        site_type=row.site_type,
        status=row.status,
        position=GeoJsonGeometry.model_validate(row.position),
        position_source=row.position_source,
        position_accuracy_m=row.position_accuracy_m,
        sharing_policy=row.sharing_policy,
        shared_with_tenants=list(row.shared_with_tenants),
        attributes=row.attributes,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
        updated_by=row.updated_by,
    )


def _placement_out(row: DeviceRow) -> DevicePlacementOut:
    field_of_view = row.field_of_view
    return DevicePlacementOut(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        device_type=row.device_type,
        external_id=row.external_id,
        status=row.status,
        site_id=row.site_id,
        position=GeoJsonGeometry.model_validate(row.position),
        position_source=row.position_source,
        position_accuracy_m=row.position_accuracy_m,
        mounting_height_m=row.mounting_height_m,
        installed_at=row.installed_at,
        decommissioned_at=row.decommissioned_at,
        sharing_policy=row.sharing_policy,
        shared_with_tenants=list(row.shared_with_tenants),
        attributes=row.attributes,
        field_of_view=None
        if field_of_view is None
        else FieldOfViewOut(
            id=field_of_view.id,
            method=field_of_view.geometry_method,
            bearing_deg=field_of_view.bearing_deg,
            fov_deg=field_of_view.fov_deg,
            range_m=field_of_view.range_m,
            geometry=field_of_view.geometry,
            valid_during=_period(field_of_view.valid_from, field_of_view.valid_to),
        ),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
        updated_by=row.updated_by,
    )
