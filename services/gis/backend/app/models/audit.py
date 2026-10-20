"""Schema ``audit``: the append-only audit log.

Mirrors migration 20260923_0007. Who, when and for which tenant are stamped by a database trigger from
the transaction's context, so the model declares no defaults for them and the application never sets
them (``app.repositories.audit``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2.elements import WKBElement
from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Index, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_AUDIT, Base
from app.models.common import EMPTY_JSON_OBJECT, geometry


class AuditEntry(Base):
    __tablename__ = "entry"
    __table_args__ = (
        Index("ix_entry_tenant_id_occurred_at_id", "tenant_id", "occurred_at", "id"),
        Index("ix_entry_actor_subject_occurred_at", "actor_subject", "occurred_at"),
        Index("ix_entry_occurred_at_brin", "occurred_at", postgresql_using="brin"),
        Index("ix_entry_geometry_extent_gist", "geometry_extent", postgresql_using="gist"),
        {"schema": SCHEMA_AUDIT},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tenant_id: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    object_id: Mapped[str | None] = mapped_column(Text)
    actor_subject: Mapped[str] = mapped_column(Text)
    actor_client: Mapped[str | None] = mapped_column(Text)
    actor_roles: Mapped[list[str]] = mapped_column(ARRAY(Text))
    cross_tenant: Mapped[bool] = mapped_column(Boolean)
    channel: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    db_user: Mapped[str] = mapped_column(Text)
    geometry_type: Mapped[str | None] = mapped_column(Text)
    geometry_extent: Mapped[WKBElement | None] = mapped_column(geometry("POLYGON"))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=EMPTY_JSON_OBJECT)
    result_count: Mapped[int | None] = mapped_column(Integer)
