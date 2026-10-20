"""The caller of a request.

The GIS runs as an instance of the main platform, which owns users and sign-in, and is reached only
through the platform. It verifies no credentials: every request acts for one tenant - the one named in the
``X-GIS-Tenant-Id`` header, else the platform's organisation (``GIS_TENANT_ID``) - with every permission
within it (:data:`app.core.access.PLATFORM_PERMISSIONS`). Row-level security still keeps each tenant's
data apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.core.access import PLATFORM_PERMISSIONS, Permission
from app.core.errors import PermissionDeniedError
from app.core.tenancy import TenantId

TENANT_HEADER: Final = "X-GIS-Tenant-Id"
PLATFORM_SUBJECT: Final = "platform"


@dataclass(frozen=True, slots=True)
class Principal:
    """The caller: the tenants it acts for and what it may do there."""

    subject: str
    tenants: frozenset[str]
    client_id: str | None = None
    permissions: frozenset[Permission] = PLATFORM_PERMISSIONS

    @property
    def all_tenants(self) -> bool:
        return Permission.ALL_TENANTS in self.permissions

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, *permissions: Permission) -> None:
        """403 unless the caller has every one of these permissions."""
        for permission in permissions:
            if permission not in self.permissions:
                raise PermissionDeniedError(
                    f"the caller lacks the permission {permission}",
                    extensions={"requiredPermission": permission.value},
                )

    def require_tenant(self, tenant_id: str) -> TenantId:
        """The tenant, if this caller acts for it; otherwise 403."""
        if self.all_tenants or tenant_id in self.tenants:
            return TenantId(tenant_id)
        raise PermissionDeniedError(
            "the request acts for another tenant (see the X-GIS-Tenant-Id header)",
            extensions={"tenantId": tenant_id},
        )


def platform_caller(tenant: str) -> Principal:
    """A request from the main platform, acting for ``tenant``."""
    return Principal(subject=PLATFORM_SUBJECT, tenants=frozenset({tenant}))
