"""ORM models.

Every model module is imported here so that ``Base.metadata`` is complete for Alembic and for the
model/migration parity test. The migrations in ``db/migrations/versions`` are authoritative.
"""

from app.db.base import Base
from app.models.audit import AuditEntry
from app.models.events import EventGeoContext, EventGeofenceHit, EventLocation, EventZoneHit
from app.models.meta import (
    DatasetLoad,
    DataSource,
    GeometryRepair,
    Layer,
    QaFinding,
    QaRun,
    RefDataRelease,
    ReleaseArtifact,
    ReleaseArtifactSource,
    Tenant,
)
from app.models.operational import Device, DeviceFieldOfView, Geofence, Site
from app.models.reference import (
    AdminArea,
    AreaPart,
    Facility,
    ProtectedArea,
    RiskZone,
    Road,
    Settlement,
    WaterBody,
)

__all__ = [
    "AdminArea",
    "AreaPart",
    "AuditEntry",
    "Base",
    "DataSource",
    "DatasetLoad",
    "Device",
    "DeviceFieldOfView",
    "EventGeoContext",
    "EventGeofenceHit",
    "EventLocation",
    "EventZoneHit",
    "Facility",
    "Geofence",
    "GeometryRepair",
    "Layer",
    "ProtectedArea",
    "QaFinding",
    "QaRun",
    "RefDataRelease",
    "ReleaseArtifact",
    "ReleaseArtifactSource",
    "RiskZone",
    "Road",
    "Settlement",
    "Site",
    "Tenant",
    "WaterBody",
]
