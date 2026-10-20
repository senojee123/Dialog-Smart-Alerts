"""Reading and writing tenant-owned operational data: geofences, sites, devices and fields of view.

Every statement runs in a transaction whose tenant is set, so row-level security decides what is
visible and writable: a tenant reads its own objects plus those shared with it, and writes only its own.
Derived geometry is left to the database - the geofence search polygons and modelled fields of view are
computed by triggers from the definition, which is why the definition is what gets stored.

Reads return geometry as GeoJSON (``ST_AsGeoJSON``), so nothing has to be converted twice on the way
out. Writes bind geometry as WKB.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import Text

from app.repositories.spatial_query import GEOJSON_DECIMALS, Bbox, Where, add_bbox, escape_like

GEOFENCE_EXTERNAL_ID_UNIQUE: Final = "uq_geofence_tenant_id_external_id"
SITE_EXTERNAL_ID_UNIQUE: Final = "uq_site_tenant_id_external_id"
DEVICE_EXTERNAL_ID_UNIQUE: Final = "uq_device_tenant_id_external_id"
DEVICE_SITE_FOREIGN_KEY: Final = "fk_device_site_id_tenant_id_site"
# Every ops table references meta.tenant; a tenant that was authorised but never registered hits these.
TENANT_FOREIGN_KEYS: Final = frozenset(
    {
        "fk_geofence_tenant_id_tenant",
        "fk_site_tenant_id_tenant",
        "fk_device_tenant_id_tenant",
        "fk_device_field_of_view_tenant_id_tenant",
    }
)
FIELD_OF_VIEW_OVERLAP: Final = "ex_device_field_of_view_device_id_valid_during"
# A device id is chosen by the client, so it can collide with a device the tenant cannot see.
DEVICE_ID_PRIMARY_KEY: Final = "pk_device"

_GEOFENCE_COLUMNS: Final = f"""
    t.id, t.tenant_id, t.name, t.description, t.external_id, t.geofence_kind,
    public.ST_AsGeoJSON(t.definition_geom, {GEOJSON_DECIMALS})::jsonb AS definition,
    t.radius_m, t.area_m2, t.status,
    lower(t.effective_during) AS effective_from, upper(t.effective_during) AS effective_to,
    t.sharing_policy, t.shared_with_tenants, t.attributes, t.version,
    t.created_at, t.updated_at, t.created_by, t.updated_by
"""
_SITE_COLUMNS: Final = f"""
    t.id, t.tenant_id, t.name, t.external_id, t.site_type, t.status,
    public.ST_AsGeoJSON(t.geom, {GEOJSON_DECIMALS})::jsonb AS position,
    t.position_source, t.position_accuracy_m,
    t.sharing_policy, t.shared_with_tenants, t.attributes, t.version,
    t.created_at, t.updated_at, t.created_by, t.updated_by
"""
_DEVICE_COLUMNS: Final = f"""
    t.id, t.tenant_id, t.name, t.device_type, t.external_id, t.status, t.site_id,
    public.ST_AsGeoJSON(t.geom, {GEOJSON_DECIMALS})::jsonb AS position,
    t.position_source, t.position_accuracy_m, t.mounting_height_m, t.installed_at, t.decommissioned_at,
    t.sharing_policy, t.shared_with_tenants, t.attributes, t.version,
    t.created_at, t.updated_at, t.created_by, t.updated_by
"""
_FIELD_OF_VIEW_COLUMNS: Final = f"""
    f.id AS field_of_view_id, f.geometry_method, f.bearing_deg, f.fov_deg, f.range_m,
    public.ST_AsGeoJSON(f.geom, {GEOJSON_DECIMALS})::jsonb AS field_of_view_geometry,
    lower(f.valid_during) AS field_of_view_from, upper(f.valid_during) AS field_of_view_to
"""
# Geometry columns are typed by the driver, so the parsed result columns are declared once.
_GEOMETRY_COLUMNS: Final[dict[str, TypeEngine[Any] | type[TypeEngine[Any]]]] = {
    "id": UUID,
    "definition": JSONB,
    "position": JSONB,
    "attributes": JSONB,
    "shared_with_tenants": ARRAY(Text),
}
_DEVICE_RESULT_COLUMNS: Final[dict[str, TypeEngine[Any] | type[TypeEngine[Any]]]] = {
    **_GEOMETRY_COLUMNS,
    "site_id": UUID,
    "field_of_view_id": UUID,
    "field_of_view_geometry": JSONB,
}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, Decimal | int | float) else None


@dataclass(frozen=True, slots=True)
class OwnedRow:
    """The parts every operational object has."""

    id: uuid.UUID
    tenant_id: str
    name: str
    external_id: str | None
    sharing_policy: str
    shared_with_tenants: tuple[str, ...]
    attributes: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


@dataclass(frozen=True, slots=True)
class GeofenceRow(OwnedRow):
    description: str | None = None
    geofence_kind: str = "polygon"
    definition: dict[str, Any] = field(default_factory=dict)
    radius_m: float | None = None
    area_m2: float = 0.0
    status: str = "active"
    effective_from: datetime | None = None
    effective_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class SiteRow(OwnedRow):
    site_type: str = "other"
    status: str = "active"
    position: dict[str, Any] = field(default_factory=dict)
    position_source: str = "gps"
    position_accuracy_m: float | None = None


@dataclass(frozen=True, slots=True)
class FieldOfViewRow:
    id: uuid.UUID
    geometry_method: str
    bearing_deg: float | None
    fov_deg: float | None
    range_m: float | None
    geometry: dict[str, Any] | None
    valid_from: datetime | None
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class DeviceRow(OwnedRow):
    device_type: str = "camera"
    status: str = "active"
    site_id: uuid.UUID | None = None
    position: dict[str, Any] = field(default_factory=dict)
    position_source: str = "gps"
    position_accuracy_m: float | None = None
    mounting_height_m: float | None = None
    installed_at: datetime | None = None
    decommissioned_at: datetime | None = None
    field_of_view: FieldOfViewRow | None = None


@dataclass(frozen=True, slots=True)
class OwnershipValues:
    sharing_policy: str
    shared_with_tenants: list[str]


@dataclass(frozen=True, slots=True)
class GeofenceValues:
    """A geofence as it should be stored. ``definition_wkb`` is the validated EPSG:4326 geometry."""

    name: str
    description: str | None
    external_id: str | None
    geofence_kind: str
    definition_wkb: bytes
    radius_m: float | None
    status: str
    effective_from: datetime | None
    effective_to: datetime | None
    ownership: OwnershipValues
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SiteValues:
    name: str
    external_id: str | None
    site_type: str
    status: str
    position_wkb: bytes
    position_source: str
    position_accuracy_m: float | None
    ownership: OwnershipValues
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DeviceValues:
    name: str
    device_type: str
    external_id: str | None
    status: str
    site_id: uuid.UUID | None
    position_wkb: bytes
    position_source: str
    position_accuracy_m: float | None
    mounting_height_m: float | None
    installed_at: datetime | None
    decommissioned_at: datetime | None
    ownership: OwnershipValues
    attributes: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FieldOfViewValues:
    geometry_method: str
    bearing_deg: float | None
    fov_deg: float | None
    range_m: float | None
    geometry_wkb: bytes | None


@dataclass(frozen=True, slots=True)
class ListFilters:
    """Filters the list endpoints share. ``status``/``kind`` values are checked by the schema."""

    limit: int
    status: str | None = None
    kind: str | None = None
    site_type: str | None = None
    name_contains: str | None = None
    bbox: Bbox | None = None
    at: datetime | None = None
    owned_only: bool = False
    after_id: uuid.UUID | None = None


def _ownership_params(ownership: OwnershipValues) -> dict[str, Any]:
    return {
        "sharing_policy": ownership.sharing_policy,
        "shared_with": list(ownership.shared_with_tenants),
    }


def _owned(row: Any) -> dict[str, Any]:
    return {
        "id": uuid.UUID(str(row.id)),
        "tenant_id": row.tenant_id,
        "name": row.name,
        "external_id": row.external_id,
        "sharing_policy": row.sharing_policy,
        "shared_with_tenants": tuple(row.shared_with_tenants),
        "attributes": dict(row.attributes),
        "version": int(row.version),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
    }


def _geofence(row: Any) -> GeofenceRow:
    return GeofenceRow(
        **_owned(row),
        description=row.description,
        geofence_kind=row.geofence_kind,
        definition=dict(row.definition),
        radius_m=_number(row.radius_m),
        area_m2=float(row.area_m2),
        status=row.status,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
    )


def _site(row: Any) -> SiteRow:
    return SiteRow(
        **_owned(row),
        site_type=row.site_type,
        status=row.status,
        position=dict(row.position),
        position_source=row.position_source,
        position_accuracy_m=_number(row.position_accuracy_m),
    )


def _field_of_view(row: Any) -> FieldOfViewRow | None:
    if row.field_of_view_id is None:
        return None
    return FieldOfViewRow(
        id=uuid.UUID(str(row.field_of_view_id)),
        geometry_method=row.geometry_method,
        bearing_deg=_number(row.bearing_deg),
        fov_deg=_number(row.fov_deg),
        range_m=_number(row.range_m),
        geometry=row.field_of_view_geometry,
        valid_from=row.field_of_view_from,
        valid_to=row.field_of_view_to,
    )


def _device(row: Any) -> DeviceRow:
    return DeviceRow(
        **_owned(row),
        device_type=row.device_type,
        status=row.status,
        site_id=None if row.site_id is None else uuid.UUID(str(row.site_id)),
        position=dict(row.position),
        position_source=row.position_source,
        position_accuracy_m=_number(row.position_accuracy_m),
        mounting_height_m=_number(row.mounting_height_m),
        installed_at=row.installed_at,
        decommissioned_at=row.decommissioned_at,
        field_of_view=_field_of_view(row),
    )


_INSERT_GEOFENCE = text(
    f"""
    INSERT INTO ops.geofence AS t (
        name, description, external_id, geofence_kind, definition_geom, radius_m, status,
        effective_during, sharing_policy, shared_with_tenants, attributes, created_by, updated_by
    ) VALUES (
        :name, :description, :external_id, :geofence_kind,
        public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326), CAST(:radius_m AS numeric), :status,
        tstzrange(coalesce(CAST(:effective_from AS timestamptz), now()),
                  CAST(:effective_to AS timestamptz)),
        :sharing_policy, :shared_with, CAST(:attributes AS jsonb), :actor, :actor
    )
    RETURNING {_GEOFENCE_COLUMNS}
    """  # noqa: S608 - constant identifiers; every value is a bound parameter
).bindparams(bindparam("shared_with", type_=ARRAY(Text)))

_UPDATE_GEOFENCE = text(
    f"""
    UPDATE ops.geofence AS t
    SET name = :name, description = :description, external_id = :external_id,
        geofence_kind = :geofence_kind,
        definition_geom = public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326),
        radius_m = CAST(:radius_m AS numeric), status = :status,
        effective_during = tstzrange(
            coalesce(CAST(:effective_from AS timestamptz), lower(t.effective_during)),
            CAST(:effective_to AS timestamptz)),
        sharing_policy = :sharing_policy, shared_with_tenants = :shared_with,
        attributes = CAST(:attributes AS jsonb), updated_by = :actor
    WHERE t.id = CAST(:id AS uuid) AND t.version = CAST(:version AS integer)
    RETURNING {_GEOFENCE_COLUMNS}
    """  # noqa: S608 - constant identifiers; every value is a bound parameter
).bindparams(bindparam("shared_with", type_=ARRAY(Text)))

_GET_GEOFENCE = text(f"SELECT {_GEOFENCE_COLUMNS} FROM ops.geofence AS t WHERE t.id = CAST(:id AS uuid)")  # noqa: S608

_ARCHIVE_GEOFENCE = text(
    """
    UPDATE ops.geofence SET status = 'archived', updated_by = :actor
    WHERE id = CAST(:id AS uuid)
      AND (CAST(:version AS integer) IS NULL OR version = CAST(:version AS integer))
    RETURNING id
    """
)
_DELETE_GEOFENCE = text("DELETE FROM ops.geofence WHERE id = CAST(:id AS uuid) RETURNING id")

_INSERT_SITE = text(
    f"""
    INSERT INTO ops.site AS t (
        name, external_id, site_type, status, geom, position_source, position_accuracy_m,
        sharing_policy, shared_with_tenants, attributes, created_by, updated_by
    ) VALUES (
        :name, :external_id, :site_type, :status, public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326),
        :position_source, CAST(:position_accuracy_m AS numeric),
        :sharing_policy, :shared_with, CAST(:attributes AS jsonb), :actor, :actor
    )
    RETURNING {_SITE_COLUMNS}
    """  # noqa: S608 - constant identifiers; every value is a bound parameter
).bindparams(bindparam("shared_with", type_=ARRAY(Text)))

_UPDATE_SITE = text(
    f"""
    UPDATE ops.site AS t
    SET name = :name, external_id = :external_id, site_type = :site_type, status = :status,
        geom = public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326),
        position_source = :position_source,
        position_accuracy_m = CAST(:position_accuracy_m AS numeric),
        sharing_policy = :sharing_policy, shared_with_tenants = :shared_with,
        attributes = CAST(:attributes AS jsonb), updated_by = :actor
    WHERE t.id = CAST(:id AS uuid) AND t.version = CAST(:version AS integer)
    RETURNING {_SITE_COLUMNS}
    """  # noqa: S608 - constant identifiers; every value is a bound parameter
).bindparams(bindparam("shared_with", type_=ARRAY(Text)))

_GET_SITE = text(f"SELECT {_SITE_COLUMNS} FROM ops.site AS t WHERE t.id = CAST(:id AS uuid)")  # noqa: S608
_DECOMMISSION_SITE = text(
    """
    UPDATE ops.site SET status = 'decommissioned', updated_by = :actor
    WHERE id = CAST(:id AS uuid)
      AND (CAST(:version AS integer) IS NULL OR version = CAST(:version AS integer))
    RETURNING id
    """
)
_DELETE_SITE = text("DELETE FROM ops.site WHERE id = CAST(:id AS uuid) RETURNING id")

_GET_DEVICE = text(
    f"""
    SELECT {_DEVICE_COLUMNS}, {_FIELD_OF_VIEW_COLUMNS}
    FROM ops.device AS t
    LEFT JOIN ops.device_field_of_view AS f
           ON f.device_id = t.id AND f.valid_during @> coalesce(CAST(:at AS timestamptz), now())
    WHERE t.id = CAST(:id AS uuid)
    """  # noqa: S608 - constant identifiers; every value is a bound parameter
)

_INSERT_DEVICE = text(
    f"""
    INSERT INTO ops.device AS t (
        id, name, device_type, external_id, status, site_id, geom, position_source, position_accuracy_m,
        mounting_height_m, installed_at, decommissioned_at, sharing_policy, shared_with_tenants,
        attributes, created_by, updated_by
    ) VALUES (
        CAST(:id AS uuid), :name, :device_type, :external_id, :status, CAST(:site_id AS uuid),
        public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326), :position_source,
        CAST(:position_accuracy_m AS numeric), CAST(:mounting_height_m AS numeric),
        CAST(:installed_at AS timestamptz), CAST(:decommissioned_at AS timestamptz),
        :sharing_policy, :shared_with, CAST(:attributes AS jsonb), :actor, :actor
    )
    RETURNING {_DEVICE_COLUMNS}
    """  # noqa: S608 - constant identifiers; every value is a bound parameter
).bindparams(bindparam("shared_with", type_=ARRAY(Text)))

_UPDATE_DEVICE = text(
    f"""
    UPDATE ops.device AS t
    SET name = :name, device_type = :device_type, external_id = :external_id, status = :status,
        site_id = CAST(:site_id AS uuid), geom = public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326),
        position_source = :position_source,
        position_accuracy_m = CAST(:position_accuracy_m AS numeric),
        mounting_height_m = CAST(:mounting_height_m AS numeric),
        installed_at = CAST(:installed_at AS timestamptz),
        decommissioned_at = CAST(:decommissioned_at AS timestamptz),
        sharing_policy = :sharing_policy, shared_with_tenants = :shared_with,
        attributes = CAST(:attributes AS jsonb), updated_by = :actor
    WHERE t.id = CAST(:id AS uuid) AND t.version = CAST(:version AS integer)
    RETURNING {_DEVICE_COLUMNS}
    """  # noqa: S608 - constant identifiers; every value is a bound parameter
).bindparams(bindparam("shared_with", type_=ARRAY(Text)))

# Closing a period never leaves it empty: a period that started in this transaction ends a microsecond
# later (ck_device_field_of_view_valid_during refuses an empty range).
_CLOSE_FIELD_OF_VIEW = text(
    """
    UPDATE ops.device_field_of_view
    SET valid_during = tstzrange(
            lower(valid_during),
            greatest(now(), lower(valid_during) + interval '1 microsecond')),
        updated_by = :actor
    WHERE device_id = CAST(:device_id AS uuid) AND upper_inf(valid_during)
    RETURNING id
    """
)
_INSERT_FIELD_OF_VIEW = text(
    """
    INSERT INTO ops.device_field_of_view (
        device_id, geometry_method, bearing_deg, fov_deg, range_m, geom, valid_during,
        created_by, updated_by
    ) VALUES (
        CAST(:device_id AS uuid), :geometry_method, CAST(:bearing_deg AS numeric),
        CAST(:fov_deg AS numeric), CAST(:range_m AS numeric),
        public.ST_Multi(public.ST_GeomFromWKB(CAST(:wkb AS bytea), 4326)),
        tstzrange(now(), NULL), :actor, :actor
    )
    RETURNING id
    """
)
# A modelled field of view is computed by the a20_model_field_of_view trigger from the device position.
_INSERT_MODELLED_FIELD_OF_VIEW = text(
    """
    INSERT INTO ops.device_field_of_view (
        device_id, geometry_method, bearing_deg, fov_deg, range_m, valid_during, created_by, updated_by
    ) VALUES (
        CAST(:device_id AS uuid), 'modelled', CAST(:bearing_deg AS numeric), CAST(:fov_deg AS numeric),
        CAST(:range_m AS numeric), tstzrange(now(), NULL), :actor, :actor
    )
    RETURNING id
    """
)

_VERSION_OF = {
    "geofence": text("SELECT id, tenant_id, version FROM ops.geofence WHERE id = CAST(:id AS uuid)"),
    "site": text("SELECT id, tenant_id, version FROM ops.site WHERE id = CAST(:id AS uuid)"),
    "device": text("SELECT id, tenant_id, version FROM ops.device WHERE id = CAST(:id AS uuid)"),
}


@dataclass(frozen=True, slots=True)
class ObjectState:
    """What a write needs to know before it runs: who owns the object and which version it is at."""

    tenant_id: str
    version: int


class OperationalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- state ------------------------------------------------------------------------------------

    async def state(self, table: str, object_id: uuid.UUID) -> ObjectState | None:
        """Owner and version of an object the tenant can see, or None if there is none."""
        row = (await self._session.execute(_VERSION_OF[table], {"id": object_id})).one_or_none()
        return None if row is None else ObjectState(tenant_id=row.tenant_id, version=int(row.version))

    # --- geofences --------------------------------------------------------------------------------

    async def create_geofence(self, values: GeofenceValues, actor: str | None) -> GeofenceRow:
        row = (await self._session.execute(_INSERT_GEOFENCE, _geofence_params(values, actor=actor))).one()
        return _geofence(row)

    async def update_geofence(
        self, geofence_id: uuid.UUID, values: GeofenceValues, *, version: int, actor: str | None
    ) -> GeofenceRow | None:
        row = (
            await self._session.execute(
                _UPDATE_GEOFENCE,
                {**_geofence_params(values, actor=actor), "id": geofence_id, "version": version},
            )
        ).one_or_none()
        return None if row is None else _geofence(row)

    async def geofence(self, geofence_id: uuid.UUID) -> GeofenceRow | None:
        row = (await self._session.execute(_GET_GEOFENCE, {"id": geofence_id})).one_or_none()
        return None if row is None else _geofence(row)

    async def geofences(self, filters: ListFilters) -> tuple[GeofenceRow, ...]:
        statement, params = _list_statement(
            "ops.geofence",
            _GEOFENCE_COLUMNS,
            filters,
            kind_column="geofence_kind",
            period_column="effective_during",
        )
        rows = (await self._session.execute(statement, params)).all()
        return tuple(_geofence(row) for row in rows)

    async def archive_geofence(
        self, geofence_id: uuid.UUID, *, version: int | None, actor: str | None
    ) -> bool:
        result = await self._session.execute(
            _ARCHIVE_GEOFENCE, {"id": geofence_id, "version": version, "actor": actor}
        )
        return result.one_or_none() is not None

    async def delete_geofence(self, geofence_id: uuid.UUID) -> bool:
        result = await self._session.execute(_DELETE_GEOFENCE, {"id": geofence_id})
        return result.one_or_none() is not None

    # --- sites ------------------------------------------------------------------------------------

    async def create_site(self, values: SiteValues, actor: str | None) -> SiteRow:
        row = (await self._session.execute(_INSERT_SITE, _site_params(values, actor=actor))).one()
        return _site(row)

    async def update_site(
        self, site_id: uuid.UUID, values: SiteValues, *, version: int, actor: str | None
    ) -> SiteRow | None:
        row = (
            await self._session.execute(
                _UPDATE_SITE, {**_site_params(values, actor=actor), "id": site_id, "version": version}
            )
        ).one_or_none()
        return None if row is None else _site(row)

    async def site(self, site_id: uuid.UUID) -> SiteRow | None:
        row = (await self._session.execute(_GET_SITE, {"id": site_id})).one_or_none()
        return None if row is None else _site(row)

    async def sites(self, filters: ListFilters) -> tuple[SiteRow, ...]:
        statement, params = _list_statement("ops.site", _SITE_COLUMNS, filters, type_column="site_type")
        rows = (await self._session.execute(statement, params)).all()
        return tuple(_site(row) for row in rows)

    async def decommission_site(self, site_id: uuid.UUID, *, version: int | None, actor: str | None) -> bool:
        result = await self._session.execute(
            _DECOMMISSION_SITE, {"id": site_id, "version": version, "actor": actor}
        )
        return result.one_or_none() is not None

    async def delete_site(self, site_id: uuid.UUID) -> bool:
        result = await self._session.execute(_DELETE_SITE, {"id": site_id})
        return result.one_or_none() is not None

    # --- devices ----------------------------------------------------------------------------------

    async def device(self, device_id: uuid.UUID, at: datetime | None = None) -> DeviceRow | None:
        row = (
            await self._session.execute(
                _GET_DEVICE.columns(**_DEVICE_RESULT_COLUMNS), {"id": device_id, "at": at}
            )
        ).one_or_none()
        return None if row is None else _device(row)

    async def create_device(self, device_id: uuid.UUID, values: DeviceValues, actor: str | None) -> DeviceRow:
        row = (
            await self._session.execute(
                _INSERT_DEVICE, {**_device_params(values, actor=actor), "id": device_id}
            )
        ).one()
        return _device_without_field_of_view(row)

    async def update_device(
        self, device_id: uuid.UUID, values: DeviceValues, *, version: int, actor: str | None
    ) -> DeviceRow | None:
        row = (
            await self._session.execute(
                _UPDATE_DEVICE,
                {**_device_params(values, actor=actor), "id": device_id, "version": version},
            )
        ).one_or_none()
        return None if row is None else _device_without_field_of_view(row)

    async def replace_field_of_view(
        self, device_id: uuid.UUID, values: FieldOfViewValues, actor: str | None
    ) -> uuid.UUID:
        """Close the period in effect and start a new one now."""
        await self._session.execute(_CLOSE_FIELD_OF_VIEW, {"device_id": device_id, "actor": actor})
        params = {
            "device_id": device_id,
            "bearing_deg": values.bearing_deg,
            "fov_deg": values.fov_deg,
            "range_m": values.range_m,
            "actor": actor,
        }
        if values.geometry_wkb is None:
            row = (await self._session.execute(_INSERT_MODELLED_FIELD_OF_VIEW, params)).one()
        else:
            row = (
                await self._session.execute(
                    _INSERT_FIELD_OF_VIEW,
                    {
                        **params,
                        "geometry_method": values.geometry_method,
                        "wkb": values.geometry_wkb,
                    },
                )
            ).one()
        return uuid.UUID(str(row.id))


def _device_without_field_of_view(row: Any) -> DeviceRow:
    """A device row from an INSERT/UPDATE, which does not join the field of view."""
    return DeviceRow(
        **_owned(row),
        device_type=row.device_type,
        status=row.status,
        site_id=None if row.site_id is None else uuid.UUID(str(row.site_id)),
        position=dict(row.position),
        position_source=row.position_source,
        position_accuracy_m=_number(row.position_accuracy_m),
        mounting_height_m=_number(row.mounting_height_m),
        installed_at=row.installed_at,
        decommissioned_at=row.decommissioned_at,
    )


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _geofence_params(values: GeofenceValues, *, actor: str | None) -> dict[str, Any]:
    return {
        "name": values.name,
        "description": values.description,
        "external_id": values.external_id,
        "geofence_kind": values.geofence_kind,
        "wkb": values.definition_wkb,
        "radius_m": values.radius_m,
        "status": values.status,
        "effective_from": values.effective_from,
        "effective_to": values.effective_to,
        "attributes": _json(values.attributes),
        "actor": actor,
        **_ownership_params(values.ownership),
    }


def _site_params(values: SiteValues, *, actor: str | None) -> dict[str, Any]:
    return {
        "name": values.name,
        "external_id": values.external_id,
        "site_type": values.site_type,
        "status": values.status,
        "wkb": values.position_wkb,
        "position_source": values.position_source,
        "position_accuracy_m": values.position_accuracy_m,
        "attributes": _json(values.attributes),
        "actor": actor,
        **_ownership_params(values.ownership),
    }


def _device_params(values: DeviceValues, *, actor: str | None) -> dict[str, Any]:
    return {
        "name": values.name,
        "device_type": values.device_type,
        "external_id": values.external_id,
        "status": values.status,
        "site_id": values.site_id,
        "wkb": values.position_wkb,
        "position_source": values.position_source,
        "position_accuracy_m": values.position_accuracy_m,
        "mounting_height_m": values.mounting_height_m,
        "installed_at": values.installed_at,
        "decommissioned_at": values.decommissioned_at,
        "attributes": _json(values.attributes),
        "actor": actor,
        **_ownership_params(values.ownership),
    }


def _list_statement(
    table: str,
    columns: str,
    filters: ListFilters,
    *,
    kind_column: str | None = None,
    type_column: str | None = None,
    period_column: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    where = Where()
    if filters.status is not None:
        where.add("t.status = CAST(:status AS text)", status=filters.status)
    if filters.kind is not None and kind_column is not None:
        where.add(f"t.{kind_column} = CAST(:kind AS text)", kind=filters.kind)
    if filters.site_type is not None and type_column is not None:
        where.add(f"t.{type_column} = CAST(:site_type AS text)", site_type=filters.site_type)
    if filters.name_contains is not None:
        where.add(
            "t.name ILIKE :name_pattern ESCAPE '\\'",
            name_pattern=f"%{escape_like(filters.name_contains)}%",
        )
    add_bbox(where, "t.geom", filters.bbox)
    if filters.at is not None and period_column is not None:
        where.add(f"t.{period_column} @> CAST(:at AS timestamptz)", at=filters.at)
    if filters.owned_only:
        where.add("t.tenant_id = meta.current_tenant_id()")
    if filters.after_id is not None:
        where.add("t.id > CAST(:after_id AS uuid)", after_id=filters.after_id)
    statement = f"""
        SELECT {columns}
        FROM {table} AS t
        WHERE {where.render()}
        ORDER BY t.id
        LIMIT CAST(:limit AS integer)
    """  # noqa: S608 - constant identifiers; every value is a bound parameter
    return text(statement).columns(**_GEOMETRY_COLUMNS), {**where.params, "limit": filters.limit}
