"""Schema ``ops``: tenant-owned sites, devices, fields of view and geofences (row-level security).

Mirrors migration 20260915_0004. Geometry derived by the database:

* ``DeviceFieldOfView.geom`` for ``geometry_method = 'modelled'`` (trigger ``a20_model_field_of_view``)
* ``Geofence.geom``, ``Geofence.geom_metric`` and ``Geofence.area_m2`` (trigger ``a20_derive_geometry``)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    DateTime,
    Double,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSTZRANGE, UUID, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_OPS, Base
from app.models.common import (
    CURRENT_TENANT,
    attributes,
    created_at,
    geometry,
    metres,
    metric_twin,
    optional_text,
    updated_at,
    uuid_pk,
)

OPEN_PERIOD_FROM_NOW: Final = text("tstzrange(now(), NULL::timestamp with time zone)")


class Audited:
    """Row version, free-form attributes and change tracking columns."""

    attributes: Mapped[dict[str, Any]] = attributes()
    # Incremented by the a80_bump_row_version trigger; repositories use it for optimistic concurrency.
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_by: Mapped[str | None] = optional_text()
    updated_by: Mapped[str | None] = optional_text()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class TenantShared(Audited):
    """Owning tenant and sharing policy (see the row-level security policies in migration 0004)."""

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[str] = mapped_column(Text, server_default=CURRENT_TENANT)
    sharing_policy: Mapped[str] = mapped_column(Text, server_default=text("'private'::text"))
    shared_with_tenants: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    external_id: Mapped[str | None] = optional_text()
    name: Mapped[str] = mapped_column(Text)


def _tenant_table_args(*extra: Any) -> tuple[Any, ...]:
    return (
        UniqueConstraint("id", "tenant_id"),
        UniqueConstraint("tenant_id", "external_id"),
        ForeignKeyConstraint(["tenant_id"], ["meta.tenant.tenant_id"], ondelete="RESTRICT"),
        *extra,
        {"schema": SCHEMA_OPS},
    )


def _spatial_indexes(name: str, *columns: str) -> tuple[Index, ...]:
    return tuple(Index(f"ix_{name}_{column}_gist", column, postgresql_using="gist") for column in columns)


class Site(TenantShared, Base):
    __tablename__ = "site"
    __table_args__ = _tenant_table_args(*_spatial_indexes("site", "geom", "geom_metric"))

    site_type: Mapped[str] = mapped_column(Text, server_default=text("'other'::text"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    geom: Mapped[WKBElement] = mapped_column(geometry("POINT"))
    geom_metric: Mapped[WKBElement] = metric_twin("POINT")
    position_source: Mapped[str] = mapped_column(Text)
    position_accuracy_m: Mapped[Decimal | None] = metres()


class Device(TenantShared, Base):
    __tablename__ = "device"
    __table_args__ = _tenant_table_args(
        ForeignKeyConstraint(
            ["site_id", "tenant_id"], ["ops.site.id", "ops.site.tenant_id"], ondelete="SET NULL (site_id)"
        ),
        Index("ix_device_site_id", "site_id"),
        *_spatial_indexes("device", "geom", "geom_metric"),
    )

    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    device_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    mounting_height_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    geom: Mapped[WKBElement] = mapped_column(geometry("POINT"))
    geom_metric: Mapped[WKBElement] = metric_twin("POINT")
    position_source: Mapped[str] = mapped_column(Text)
    position_accuracy_m: Mapped[Decimal | None] = metres()
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decommissioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceFieldOfView(Audited, Base):
    __tablename__ = "device_field_of_view"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        ForeignKeyConstraint(["tenant_id"], ["meta.tenant.tenant_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["device_id", "tenant_id"], ["ops.device.id", "ops.device.tenant_id"], ondelete="CASCADE"
        ),
        ExcludeConstraint(
            ("device_id", "="),
            ("valid_during", "&&"),
            name="ex_device_field_of_view_device_id_valid_during",
            using="gist",
        ),
        *_spatial_indexes("device_field_of_view", "geom", "geom_metric"),
        {"schema": SCHEMA_OPS},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[str] = mapped_column(Text, server_default=CURRENT_TENANT)
    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    geometry_method: Mapped[str] = mapped_column(Text)
    bearing_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    fov_deg: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    range_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    # Server-derived for modelled fields of view.
    geom: Mapped[WKBElement] = mapped_column(geometry("MULTIPOLYGON"), server_default=FetchedValue())
    geom_metric: Mapped[WKBElement] = metric_twin("MULTIPOLYGON")
    valid_during: Mapped[Range[datetime]] = mapped_column(TSTZRANGE, server_default=OPEN_PERIOD_FROM_NOW)


class Geofence(TenantShared, Base):
    __tablename__ = "geofence"
    __table_args__ = _tenant_table_args(
        *_spatial_indexes("geofence", "geom", "geom_metric", "effective_during"),
        Index("ix_geofence_tenant_id_geom_gist", "tenant_id", "geom", postgresql_using="gist"),
    )

    description: Mapped[str | None] = optional_text()
    geofence_kind: Mapped[str] = mapped_column(Text)
    definition_geom: Mapped[WKBElement] = mapped_column(geometry("GEOMETRY"))
    definition_geom_metric: Mapped[WKBElement] = metric_twin("GEOMETRY", source="definition_geom")
    radius_m: Mapped[Decimal | None] = metres()
    # Derived by the database from the definition.
    geom: Mapped[WKBElement] = mapped_column(geometry("MULTIPOLYGON"), server_default=FetchedValue())
    geom_metric: Mapped[WKBElement] = mapped_column(
        geometry("MULTIPOLYGON", 5235), server_default=FetchedValue()
    )
    area_m2: Mapped[float] = mapped_column(Double, server_default=FetchedValue())
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'::text"))
    effective_during: Mapped[Range[datetime]] = mapped_column(TSTZRANGE, server_default=OPEN_PERIOD_FROM_NOW)


OPERATIONAL_MODELS: Final = (Site, Device, DeviceFieldOfView, Geofence)
