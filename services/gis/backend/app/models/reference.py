"""Schema ``ref``: national reference data, versioned by release. Read-only for the API.

Mirrors migration 20260915_0003.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TSTZRANGE, UUID, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_REF, Base
from app.models.common import (
    attributes,
    created_at,
    geometry,
    metres,
    metric_twin,
    optional_text,
    updated_at,
    uuid_pk,
)

AREA_KINDS: Final = ("admin_area", "protected_area", "risk_zone", "water_body")
ADMIN_LEVEL_NAMES: Final = {0: "country", 1: "province", 2: "district", 3: "ds_division", 4: "gn_division"}


def _table_args(name: str, *extra: Any) -> tuple[Any, ...]:
    """Keys and indexes every reference table has (see ``_create`` in migration 0003)."""
    return (
        UniqueConstraint("id", "release_id"),
        UniqueConstraint("release_id", "source_feature_id"),
        ForeignKeyConstraint(
            ["load_id", "release_id"],
            ["meta.dataset_load.id", "meta.dataset_load.release_id"],
            ondelete="CASCADE",
        ),
        Index(f"ix_{name}_release_id_geom_gist", "release_id", "geom", postgresql_using="gist"),
        Index(f"ix_{name}_release_id_geom_metric_gist", "release_id", "geom_metric", postgresql_using="gist"),
        Index(f"ix_{name}_load_id", "load_id"),
        *extra,
        {"schema": SCHEMA_REF},
    )


class ReferenceFeature:
    """Columns shared by every reference layer. ``geom``/``geom_metric`` are declared per layer."""

    id: Mapped[uuid.UUID] = uuid_pk()
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    load_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_feature_id: Mapped[str | None] = optional_text()
    name_si: Mapped[str | None] = optional_text()
    name_ta: Mapped[str | None] = optional_text()
    geometry_source: Mapped[str] = mapped_column(Text, server_default=text("'unknown'::text"))
    geometry_accuracy_m: Mapped[Decimal | None] = metres()
    attributes: Mapped[dict[str, Any]] = attributes()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AdminArea(ReferenceFeature, Base):
    __tablename__ = "admin_area"
    __table_args__ = _table_args(
        "admin_area",
        UniqueConstraint("release_id", "level", "code"),
        ForeignKeyConstraint(["parent_id", "release_id"], ["ref.admin_area.id", "ref.admin_area.release_id"]),
        Index("ix_admin_area_parent_id", "parent_id"),
    )

    name: Mapped[str] = mapped_column(Text)
    level: Mapped[int] = mapped_column(SmallInteger)
    level_name: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            "CASE level WHEN 0 THEN 'country'::text WHEN 1 THEN 'province'::text "
            "WHEN 2 THEN 'district'::text WHEN 3 THEN 'ds_division'::text WHEN 4 THEN 'gn_division'::text "
            "ELSE NULL::text END",
            persisted=True,
        ),
    )
    code: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    geom: Mapped[WKBElement] = mapped_column(geometry("MULTIPOLYGON"))
    geom_metric: Mapped[WKBElement] = metric_twin("MULTIPOLYGON")


class Settlement(ReferenceFeature, Base):
    __tablename__ = "settlement"
    __table_args__ = _table_args(
        "settlement",
        ForeignKeyConstraint(
            ["admin_area_id", "release_id"], ["ref.admin_area.id", "ref.admin_area.release_id"]
        ),
        Index("ix_settlement_admin_area_id", "admin_area_id"),
    )

    name: Mapped[str] = mapped_column(Text)
    settlement_type: Mapped[str] = mapped_column(Text)
    population: Mapped[int | None] = mapped_column(Integer)
    population_year: Mapped[int | None] = mapped_column(SmallInteger)
    admin_area_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    geometry_basis: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            "CASE WHEN geometrytype(geom) = 'POINT'::text THEN 'point'::text ELSE 'footprint'::text END",
            persisted=True,
        ),
    )
    label_point: Mapped[WKBElement | None] = mapped_column(
        geometry("POINT"),
        Computed(
            "CASE WHEN geometrytype(geom) = 'POINT'::text THEN geom ELSE st_pointonsurface(geom) END",
            persisted=True,
        ),
    )
    geom: Mapped[WKBElement] = mapped_column(geometry("GEOMETRY"))
    geom_metric: Mapped[WKBElement] = metric_twin("GEOMETRY")


class Facility(ReferenceFeature, Base):
    __tablename__ = "facility"
    __table_args__ = _table_args(
        "facility",
        Index("ix_facility_release_id_facility_type", "release_id", "facility_type"),
    )

    name: Mapped[str] = mapped_column(Text)
    facility_type: Mapped[str] = mapped_column(Text)
    geom: Mapped[WKBElement] = mapped_column(geometry("POINT"))
    geom_metric: Mapped[WKBElement] = metric_twin("POINT")


class Road(ReferenceFeature, Base):
    __tablename__ = "road"
    __table_args__ = _table_args("road")

    name: Mapped[str | None] = optional_text()
    road_class: Mapped[str] = mapped_column(Text, server_default=text("'unknown'::text"))
    ref_code: Mapped[str | None] = optional_text()
    osm_highway: Mapped[str | None] = optional_text()
    geom: Mapped[WKBElement] = mapped_column(geometry("MULTILINESTRING"))
    geom_metric: Mapped[WKBElement] = metric_twin("MULTILINESTRING")


class WaterBody(ReferenceFeature, Base):
    __tablename__ = "water_body"
    __table_args__ = _table_args("water_body")

    name: Mapped[str | None] = optional_text()
    water_type: Mapped[str] = mapped_column(Text)
    geometry_kind: Mapped[str | None] = mapped_column(
        Text,
        Computed(
            "CASE WHEN geometrytype(geom) = 'MULTILINESTRING'::text THEN 'line'::text ELSE 'area'::text END",
            persisted=True,
        ),
    )
    geom: Mapped[WKBElement] = mapped_column(geometry("GEOMETRY"))
    geom_metric: Mapped[WKBElement] = metric_twin("GEOMETRY")


class ProtectedArea(ReferenceFeature, Base):
    __tablename__ = "protected_area"
    __table_args__ = _table_args("protected_area")

    name: Mapped[str] = mapped_column(Text)
    designation: Mapped[str] = mapped_column(Text)
    managing_authority: Mapped[str] = mapped_column(Text)
    iucn_category: Mapped[str | None] = optional_text()
    designated_on: Mapped[date | None] = mapped_column(Date)
    geom: Mapped[WKBElement] = mapped_column(geometry("MULTIPOLYGON"))
    geom_metric: Mapped[WKBElement] = metric_twin("MULTIPOLYGON")


class RiskZone(ReferenceFeature, Base):
    __tablename__ = "risk_zone"
    __table_args__ = _table_args(
        "risk_zone",
        Index("ix_risk_zone_valid_during_gist", "valid_during", postgresql_using="gist"),
    )

    name: Mapped[str] = mapped_column(Text)
    risk_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[int] = mapped_column(SmallInteger)
    valid_during: Mapped[Range[datetime]] = mapped_column(
        TSTZRANGE,
        server_default=text("tstzrange(NULL::timestamp with time zone, NULL::timestamp with time zone)"),
    )
    geom: Mapped[WKBElement] = mapped_column(geometry("MULTIPOLYGON"))
    geom_metric: Mapped[WKBElement] = metric_twin("MULTIPOLYGON")


class AreaPart(Base):
    """Subdivided polygons of the area layers; written only by the ``z10_sync_area_part`` triggers."""

    __tablename__ = "area_part"
    __table_args__ = (
        Index(
            "ix_area_part_release_id_area_kind_geom_gist",
            "release_id",
            "area_kind",
            "geom",
            postgresql_using="gist",
        ),
        Index("ix_area_part_feature_id", "feature_id"),
        {"schema": SCHEMA_REF},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    area_kind: Mapped[str] = mapped_column(Text)
    feature_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    geom: Mapped[WKBElement] = mapped_column(geometry("POLYGON"))


REFERENCE_MODELS: Final = (AdminArea, Settlement, Facility, Road, WaterBody, ProtectedArea, RiskZone)
