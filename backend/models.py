"""
ORM models (Stage B1).

Hybrid "document + indexed projections" layout: the full record lives in a JSON
`data` column (so the flexible, schemaless shape the app already uses is preserved),
while the columns the hot paths filter/sort on are mirrored out as real, indexed
columns. `MIRROR` lists which keys are projected from `data` into columns on write.

Timestamps are stored as ISO-8601 UTC strings (consistent format → correct
lexicographic range/sort on both SQLite and Postgres).
"""

from sqlalchemy import String, Float, Boolean, Integer, Index, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UseCase(Base):
    __tablename__ = "use_cases"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    active: Mapped[bool | None] = mapped_column(Boolean, index=True)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = ["active"]


class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    use_case_id: Mapped[str | None] = mapped_column(String, index=True)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = ["use_case_id"]


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    use_case_id: Mapped[str | None] = mapped_column(String, index=True)
    zone_id: Mapped[str | None] = mapped_column(String, index=True)
    external_id: Mapped[str | None] = mapped_column(String, index=True)
    type: Mapped[str | None] = mapped_column(String)
    online: Mapped[bool | None] = mapped_column(Boolean)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = ["use_case_id", "zone_id", "external_id", "type", "online"]


class RoadSign(Base):
    __tablename__ = "road_signs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    zone_id: Mapped[str | None] = mapped_column(String, index=True)
    online: Mapped[bool | None] = mapped_column(Boolean)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = ["zone_id", "online"]


class Stakeholder(Base):
    __tablename__ = "stakeholders"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = []


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    use_case_id: Mapped[str | None] = mapped_column(String, index=True)
    active: Mapped[bool | None] = mapped_column(Boolean)
    priority: Mapped[int | None] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = ["use_case_id", "active", "priority"]


class DetectionEvent(Base):
    __tablename__ = "detection_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    use_case_id: Mapped[str | None] = mapped_column(String)
    zone_id: Mapped[str | None] = mapped_column(String)
    device_id: Mapped[str | None] = mapped_column(String, index=True)
    source: Mapped[str | None] = mapped_column(String, index=True)
    client_event_id: Mapped[str | None] = mapped_column(String, index=True)
    object_type: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    processed: Mapped[bool | None] = mapped_column(Boolean)
    received_at: Mapped[str | None] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = ["use_case_id", "zone_id", "device_id", "source", "client_event_id",
              "object_type", "confidence", "lat", "lng", "processed", "received_at"]
    __table_args__ = (
        Index("ix_events_uc_zone_time", "use_case_id", "zone_id", "received_at"),
        Index("ix_events_recent", "received_at"),
    )


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    use_case_id: Mapped[str | None] = mapped_column(String)
    zone_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    severity: Mapped[str | None] = mapped_column(String)
    simulated: Mapped[bool | None] = mapped_column(Boolean)
    opened_at: Mapped[str | None] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = ["use_case_id", "zone_id", "status", "severity", "simulated", "opened_at"]
    __table_args__ = (
        Index("ix_incidents_status_uc_time", "status", "use_case_id", "opened_at"),
        Index("ix_incidents_zone_uc_status", "zone_id", "use_case_id", "status"),
    )


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[str | None] = mapped_column(String, index=True)
    sent_at: Mapped[str | None] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)
    MIRROR = ["incident_id", "sent_at"]


# table name → model, used by the generic repository
MODELS = {
    "use_cases":        UseCase,
    "zones":            Zone,
    "devices":          Device,
    "road_signs":       RoadSign,
    "stakeholders":     Stakeholder,
    "rules":            Rule,
    "detection_events": DetectionEvent,
    "incidents":        Incident,
    "notifications":    Notification,
}
