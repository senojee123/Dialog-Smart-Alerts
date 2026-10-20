"""Schema ``geo``: event locations and geo-context, partitioned by month of ``observed_at`` (UTC).

Mirrors migration 20260915_0005. Partitions (``<table>_pYYYYMM``) are created at runtime by
``geo.ensure_event_partition()`` and are not mapped.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from geoalchemy2.elements import WKBElement
from sqlalchemy import Computed, DateTime, ForeignKeyConstraint, Index, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_GEO, Base
from app.models.common import CURRENT_TENANT, NOW, attributes, geometry, metres, metric_twin, optional_text

PARTITION_BY: Final = "RANGE (observed_at)"
EVENT_KEY: Final = ("tenant_id", "event_id", "observed_at")


class EventLocation(Base):
    __tablename__ = "event_location"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["meta.tenant.tenant_id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["device_id", "tenant_id"], ["ops.device.id", "ops.device.tenant_id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["field_of_view_id", "tenant_id"],
            ["ops.device_field_of_view.id", "ops.device_field_of_view.tenant_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_event_location_tenant_id_observed_at", "tenant_id", "observed_at"),
        Index("ix_event_location_tenant_id_event_type_observed_at", "tenant_id", "event_type", "observed_at"),
        Index(
            "ix_event_location_device_id_observed_at",
            "device_id",
            "observed_at",
            postgresql_where=text("device_id IS NOT NULL"),
        ),
        Index(
            "ix_event_location_field_of_view_id",
            "field_of_view_id",
            postgresql_where=text("field_of_view_id IS NOT NULL"),
        ),
        Index("ix_event_location_observed_at_brin", "observed_at", postgresql_using="brin"),
        Index("ix_event_location_geom_gist", "geom", postgresql_using="gist"),
        Index("ix_event_location_geom_metric_gist", "geom_metric", postgresql_using="gist"),
        {"schema": SCHEMA_GEO, "postgresql_partition_by": PARTITION_BY},
    )

    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=CURRENT_TENANT)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    event_subtype: Mapped[str | None] = optional_text()
    source_type: Mapped[str] = mapped_column(Text)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_ref: Mapped[str | None] = optional_text()
    location_source: Mapped[str] = mapped_column(Text)
    geom: Mapped[WKBElement] = mapped_column(geometry("GEOMETRY"))
    geom_metric: Mapped[WKBElement] = metric_twin("GEOMETRY")
    geometry_kind: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            "CASE st_dimension(geom) WHEN 0 THEN 'point'::text WHEN 1 THEN 'line'::text "
            "ELSE 'area'::text END",
            persisted=True,
        ),
    )
    location_accuracy_m: Mapped[Decimal | None] = metres()
    field_of_view_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    field_of_view: Mapped[WKBElement | None] = mapped_column(geometry("MULTIPOLYGON"))
    attributes: Mapped[dict[str, Any]] = attributes()
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class EventGeoContext(Base):
    __tablename__ = "event_geo_context"
    __table_args__ = (
        ForeignKeyConstraint(
            list(EVENT_KEY), [f"geo.event_location.{column}" for column in EVENT_KEY], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["release_id"], ["meta.ref_data_release.id"], ondelete="RESTRICT"),
        Index("ix_event_geo_context_release_id", "release_id"),
        Index(
            "ix_event_geo_context_tenant_id_admin_l2_id_observed_at",
            "tenant_id",
            "admin_l2_id",
            "observed_at",
        ),
        {"schema": SCHEMA_GEO, "postgresql_partition_by": PARTITION_BY},
    )

    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    schema_version: Mapped[str] = mapped_column(Text, server_default=text("'geo-context/1'::text"))
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    release_code: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    location_source: Mapped[str] = mapped_column(Text)
    admin_l1_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    admin_l1_code: Mapped[str | None] = optional_text()
    admin_l2_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    admin_l2_code: Mapped[str | None] = optional_text()
    admin_l3_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    admin_l3_code: Mapped[str | None] = optional_text()
    admin_l4_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    admin_l4_code: Mapped[str | None] = optional_text()
    nearest_settlement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    nearest_settlement_distance_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    nearest_road_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    nearest_road_distance_m: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)


def _hit_key() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        list(EVENT_KEY), [f"geo.event_geo_context.{column}" for column in EVENT_KEY], ondelete="CASCADE"
    )


class EventZoneHit(Base):
    __tablename__ = "event_zone_hit"
    __table_args__ = (
        _hit_key(),
        Index("ix_event_zone_hit_zone_id_observed_at", "zone_id", "observed_at"),
        {"schema": SCHEMA_GEO, "postgresql_partition_by": PARTITION_BY},
    )

    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    zone_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    zone_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    relation: Mapped[str] = mapped_column(Text)


class EventGeofenceHit(Base):
    __tablename__ = "event_geofence_hit"
    __table_args__ = (
        _hit_key(),
        Index("ix_event_geofence_hit_geofence_id_observed_at", "geofence_id", "observed_at"),
        {"schema": SCHEMA_GEO, "postgresql_partition_by": PARTITION_BY},
    )

    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    # Snapshot of the geofence at computation time; no foreign key (see migration 0005).
    geofence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    geofence_tenant_id: Mapped[str] = mapped_column(Text)
    geofence_version: Mapped[int] = mapped_column(Integer)
    relation: Mapped[str] = mapped_column(Text)
