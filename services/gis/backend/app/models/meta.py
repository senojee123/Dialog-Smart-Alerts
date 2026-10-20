"""Schema ``meta``: tenants, data sources, reference data releases, layer registry, lineage and QA.

Mirrors migrations 20260915_0002 and 20260924_0008 (and the layer rows added by other revisions).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_META, Base
from app.models.common import (
    EMPTY_JSON_OBJECT,
    NOW,
    created_at,
    geometry,
    metres,
    optional_text,
    updated_at,
    uuid_pk,
)


class Tenant(Base):
    __tablename__ = "tenant"
    __table_args__ = ({"schema": SCHEMA_META},)

    tenant_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, server_default=text("'organisation'::text"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class DataSource(Base):
    __tablename__ = "data_source"
    __table_args__ = (UniqueConstraint("code"), {"schema": SCHEMA_META})

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = optional_text()
    licence: Mapped[str] = mapped_column(Text)
    licence_url: Mapped[str | None] = optional_text()
    attribution: Mapped[str] = mapped_column(Text)
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean)
    share_alike: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    permission_reference: Mapped[str | None] = optional_text()
    notes: Mapped[str | None] = optional_text()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    redistribution_allowed: Mapped[bool] = mapped_column(Boolean)
    licence_review_status: Mapped[str] = mapped_column(Text, server_default=text("'unreviewed'::text"))
    licence_reviewed_by: Mapped[str | None] = optional_text()
    licence_reviewed_on: Mapped[date | None] = mapped_column(Date)
    licence_review_reference: Mapped[str | None] = optional_text()


class RefDataRelease(Base):
    __tablename__ = "ref_data_release"
    __table_args__ = (
        UniqueConstraint("code"),
        Index(
            "uq_ref_data_release_is_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        {"schema": SCHEMA_META},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = optional_text()
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'::text"))
    is_current: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, server_default=text("CURRENT_USER"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    purpose: Mapped[str] = mapped_column(Text, server_default=text("'development'::text"))


class Layer(Base):
    __tablename__ = "layer"
    __table_args__ = (
        UniqueConstraint("code"),
        UniqueConstraint("table_schema", "table_name", "geometry_column"),
        {"schema": SCHEMA_META},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    layer_group: Mapped[str] = mapped_column(Text)
    table_schema: Mapped[str] = mapped_column(Text)
    table_name: Mapped[str] = mapped_column(Text)
    geometry_column: Mapped[str] = mapped_column(Text, server_default=text("'geom'::text"))
    geometry_types: Mapped[list[str]] = mapped_column(ARRAY(Text))
    srid: Mapped[int] = mapped_column(Integer, server_default=text("4326"))
    metric_srid: Mapped[int] = mapped_column(Integer, server_default=text("5235"))
    tenant_scoped: Mapped[bool] = mapped_column(Boolean)
    default_sharing_policy: Mapped[str | None] = optional_text()
    update_frequency: Mapped[str] = mapped_column(Text)
    nominal_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_published: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class DatasetLoad(Base):
    __tablename__ = "dataset_load"
    __table_args__ = (
        UniqueConstraint("id", "release_id"),
        ForeignKeyConstraint(["release_id"], ["meta.ref_data_release.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["layer_id"], ["meta.layer.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["source_id"], ["meta.data_source.id"], ondelete="RESTRICT"),
        Index("ix_dataset_load_release_id_layer_id", "release_id", "layer_id"),
        Index("ix_dataset_load_layer_id", "layer_id"),
        Index("ix_dataset_load_source_id", "source_id"),
        Index("ix_dataset_load_started_at", "started_at"),
        Index(
            "uq_dataset_load_file_once_per_release",
            "release_id",
            "layer_id",
            "source_checksum_sha256",
            unique=True,
            postgresql_where=text("status <> 'failed'::text"),
        ),
        {"schema": SCHEMA_META},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    layer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_version: Mapped[str | None] = optional_text()
    source_file: Mapped[str] = mapped_column(Text)
    source_checksum_sha256: Mapped[str] = mapped_column(Text)
    source_crs: Mapped[str] = mapped_column(Text)
    source_feature_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    transformation: Mapped[str] = mapped_column(Text)
    loader_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'running'::text"))
    loaded_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    repaired_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rejected_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    message: Mapped[str | None] = optional_text()
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loaded_by: Mapped[str] = mapped_column(Text, server_default=text("CURRENT_USER"))
    # Lineage added by revision 20260924_0008: the licence is a snapshot taken at load time.
    source_reference: Mapped[str] = mapped_column(Text)
    source_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_file: Mapped[str | None] = optional_text()
    original_checksum_sha256: Mapped[str | None] = optional_text()
    licence: Mapped[str] = mapped_column(Text)
    licence_url: Mapped[str | None] = optional_text()
    attribution: Mapped[str] = mapped_column(Text)
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean)
    redistribution_allowed: Mapped[bool] = mapped_column(Boolean)
    share_alike: Mapped[bool] = mapped_column(Boolean)
    permission_reference: Mapped[str | None] = optional_text()
    licence_review_status: Mapped[str] = mapped_column(Text)
    storage_crs: Mapped[str] = mapped_column(Text, server_default=text("'EPSG:4326'::text"))
    coordinate_operation: Mapped[str | None] = optional_text()
    geometry_accuracy_m: Mapped[Decimal | None] = metres()
    geometry_types: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    extent: Mapped[WKBElement | None] = mapped_column(geometry("POLYGON"))
    qa_expectations: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON_OBJECT)
    tool_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON_OBJECT)


class GeometryRepair(Base):
    __tablename__ = "geometry_repair"
    __table_args__ = (
        ForeignKeyConstraint(["load_id"], ["meta.dataset_load.id"], ondelete="CASCADE"),
        Index("ix_geometry_repair_load_id", "load_id"),
        Index(
            "ix_geometry_repair_table_schema_table_name_feature_id",
            "table_schema",
            "table_name",
            "feature_id",
        ),
        {"schema": SCHEMA_META},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    table_schema: Mapped[str] = mapped_column(Text)
    table_name: Mapped[str] = mapped_column(Text)
    feature_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    load_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text)
    original_geom: Mapped[WKBElement] = mapped_column(geometry("GEOMETRY"))
    original_area_m2: Mapped[float | None] = mapped_column(Double)
    repaired_area_m2: Mapped[float | None] = mapped_column(Double)
    repaired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=NOW)


class QaRun(Base):
    __tablename__ = "qa_run"
    __table_args__ = (
        UniqueConstraint("id", "release_id"),
        ForeignKeyConstraint(["release_id"], ["meta.ref_data_release.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["load_id", "release_id"],
            ["meta.dataset_load.id", "meta.dataset_load.release_id"],
            ondelete="CASCADE",
        ),
        Index("ix_qa_run_release_id_stage_started_at", "release_id", "stage", "started_at"),
        Index("ix_qa_run_load_id", "load_id"),
        {"schema": SCHEMA_META},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    load_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    stage: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'running'::text"))
    content_fingerprint: Mapped[str | None] = optional_text()
    check_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    warning_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    info_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON_OBJECT)
    tool_version: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_by: Mapped[str] = mapped_column(Text, server_default=text("SESSION_USER"))


class QaFinding(Base):
    __tablename__ = "qa_finding"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "release_id"], ["meta.qa_run.id", "meta.qa_run.release_id"], ondelete="CASCADE"
        ),
        Index("ix_qa_finding_run_id_severity", "run_id", "severity"),
        Index("ix_qa_finding_release_id", "release_id"),
        {"schema": SCHEMA_META},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    check_code: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    layer_code: Mapped[str | None] = optional_text()
    load_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    feature_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_feature_id: Mapped[str | None] = optional_text()
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON_OBJECT)
    location: Mapped[WKBElement | None] = mapped_column(geometry("GEOMETRY"))
    waivable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    waived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waived_by: Mapped[str | None] = optional_text()
    waiver_reason: Mapped[str | None] = optional_text()


class ReleaseArtifact(Base):
    __tablename__ = "release_artifact"
    __table_args__ = (
        UniqueConstraint("id", "release_id"),
        UniqueConstraint("release_id", "name"),
        ForeignKeyConstraint(["release_id"], ["meta.ref_data_release.id"], ondelete="CASCADE"),
        {"schema": SCHEMA_META},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    uri: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    crs: Mapped[str] = mapped_column(Text)
    min_zoom: Mapped[int | None] = mapped_column(SmallInteger)
    max_zoom: Mapped[int | None] = mapped_column(SmallInteger)
    bounds: Mapped[WKBElement | None] = mapped_column(geometry("POLYGON"))
    geometry_types: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    geometry_accuracy_m: Mapped[Decimal | None] = metres()
    transformation: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=EMPTY_JSON_OBJECT)
    tool_versions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON_OBJECT)
    created_at: Mapped[datetime] = created_at()
    created_by: Mapped[str] = mapped_column(Text, server_default=text("CURRENT_USER"))


class ReleaseArtifactSource(Base):
    __tablename__ = "release_artifact_source"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artifact_id", "release_id"],
            ["meta.release_artifact.id", "meta.release_artifact.release_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["source_id"], ["meta.data_source.id"], ondelete="RESTRICT"),
        Index("ix_release_artifact_source_source_id", "source_id"),
        {"schema": SCHEMA_META},
    )

    artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    release_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str | None] = optional_text()
    source_reference: Mapped[str] = mapped_column(Text)
    source_checksum_sha256: Mapped[str | None] = optional_text()
    source_retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    licence: Mapped[str] = mapped_column(Text)
    licence_url: Mapped[str | None] = optional_text()
    attribution: Mapped[str] = mapped_column(Text)
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean)
    redistribution_allowed: Mapped[bool] = mapped_column(Boolean)
    share_alike: Mapped[bool] = mapped_column(Boolean)
    permission_reference: Mapped[str | None] = optional_text()
    licence_review_status: Mapped[str] = mapped_column(Text)
