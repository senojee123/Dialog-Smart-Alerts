"""Permissions, and the access context a request carries into the database.

The GIS runs as an instance of the main platform, which owns users and sign-in. The GIS has no roles and
checks no credentials: every request acts with the permissions in :data:`PLATFORM_PERMISSIONS` (see
:mod:`app.core.caller`). Endpoints still name the permission they exercise (``Principal.require`` and
``x-gis-permissions`` in the OpenAPI document), so access control can be added in one place,
``app.api.deps.get_principal``, if the platform ever needs it.

**Access** is the caller plus the tenant the request acts for. Services write the access context into
transaction-local settings, where row-level security and the audit log read it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

from app.core.errors import TenantRequiredError
from app.core.tenancy import TenantId


class Permission(StrEnum):
    """What a caller may do with the GIS service."""

    MAP_READ = "map:read"
    SPATIAL_QUERY = "query:spatial"
    EVENTS_READ = "events:read"
    GEOFENCES_WRITE = "geofences:write"
    ASSETS_WRITE = "assets:write"
    DATA_PURGE = "data:purge"
    DATA_EXPORT = "data:export"
    AUDIT_READ = "audit:read"
    EVENTS_ENRICH = "events:enrich"
    ALL_TENANTS = "tenants:all"


PERMISSION_DESCRIPTIONS: Final[Mapping[Permission, str]] = {
    Permission.MAP_READ: "read the layer catalogue, map features (reference data and the tenant's "
    "operational layers) and reverse geocoding",
    Permission.SPATIAL_QUERY: "ask spatial questions: within a distance, nearest, containing",
    Permission.EVENTS_READ: "read the tenant's event locations",
    Permission.GEOFENCES_WRITE: "create, change and archive the tenant's geofences",
    Permission.ASSETS_WRITE: "create, change and decommission sites; place devices",
    Permission.DATA_PURGE: "remove geofences and sites permanently",
    Permission.DATA_EXPORT: "export layer features and events as files",
    Permission.AUDIT_READ: "read the audit records of the tenant",
    Permission.EVENTS_ENRICH: "compute and store the geo-context of events",
    Permission.ALL_TENANTS: "act for any registered tenant by naming it",
}

# Every request may do everything within the one tenant it acts for.
PLATFORM_PERMISSIONS: Final = frozenset(Permission) - {Permission.ALL_TENANTS}


Channel = Literal["api", "loader"]


@dataclass(frozen=True, slots=True)
class Actor:
    """Who performs an operation, as the audit log records it."""

    subject: str
    client_id: str | None = None
    request_id: str | None = None
    channel: Channel = "api"

    @property
    def label(self) -> str:
        """How the actor is written into ``created_by`` / ``updated_by`` of the objects it changes."""
        return f"{self.client_id}:{self.subject}" if self.client_id else self.subject


@dataclass(frozen=True, slots=True)
class Access:
    """The caller and the tenant a request acts for."""

    actor: Actor
    tenant: TenantId | None
    # True when a caller acts for a tenant that is not one of its own.
    cross_tenant: bool = False

    def required_tenant(
        self, detail: str | None = None, extensions: Mapping[str, str] | None = None
    ) -> TenantId:
        """The tenant, or 400 ``tenant_required`` for an operation on tenant data that names none."""
        if self.tenant is None:
            raise TenantRequiredError(
                detail or "this request concerns tenant data; pass tenantId",
                extensions=dict(extensions or {}),
            )
        return self.tenant

    @classmethod
    def system(cls, subject: str, tenant: TenantId | None = None, *, channel: Channel = "loader") -> Access:
        """Access for work that no request carries (command-line tools)."""
        return cls(actor=Actor(subject=subject, channel=channel), tenant=tenant)
