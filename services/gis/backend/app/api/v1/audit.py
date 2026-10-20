"""``/geo/v1/audit/entries`` and ``/geo/v1/me``: the audit log, and the caller as the service sees it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import AuditLogServiceDep, PrincipalDep, access_for
from app.api.v1.problems import other_tenant, requires
from app.core.access import Permission
from app.core.errors import TenantRequiredError
from app.schemas.audit import AuditLogOut, AuditLogQuery, IdentityOut

router = APIRouter(tags=["audit"])

_ENTRIES = "/geo/v1/audit/entries"

ENTRIES_DESCRIPTION = """
The tenant's audit log, newest first: searches, sensitive queries (reads of operational data and events),
exports, changes to geofences, sites and device placements. Each entry names the caller by subject id, the
tenant, the operation, when, the parameters and result count, and the coarse extent of any geometry
involved (a 0.001 degree grid, not the geometry itself).

Filter by `category`, `operation`, `actorSubject` and a time window; paged with `nextCursor`. Reading the
log is itself recorded.
"""


@router.get(
    "/audit/entries",
    operation_id="listAuditEntries",
    response_model=AuditLogOut,
    summary="Audit log of a tenant",
    description=ENTRIES_DESCRIPTION,
    responses={
        status.HTTP_403_FORBIDDEN: other_tenant(_ENTRIES),
    },
    openapi_extra=requires(Permission.AUDIT_READ),
)
async def list_audit_entries(
    params: Annotated[AuditLogQuery, Query()],
    principal: PrincipalDep,
    service: AuditLogServiceDep,
    response: Response,
) -> AuditLogOut:
    principal.require(Permission.AUDIT_READ)
    access = access_for(principal, params.tenant_id)
    if access.tenant is None and not principal.all_tenants:
        # Entries without a tenant are platform records; an organisation reads its own tenant's log.
        raise TenantRequiredError("the audit log belongs to a tenant; pass tenantId")
    response.headers["Cache-Control"] = "no-store"
    return await service.entries(access, params)


@router.get(
    "/me",
    operation_id="getIdentity",
    response_model=IdentityOut,
    summary="The caller's permissions and tenant",
    description="What the request may do and the tenant it acts for. A client uses it to decide what to "
    "offer. The GIS checks no credentials: requests come from the main platform, which owns sign-in.",
    openapi_extra=requires(),
)
async def get_identity(principal: PrincipalDep, response: Response) -> IdentityOut:
    response.headers["Cache-Control"] = "no-store"
    return IdentityOut(
        subject=principal.subject,
        client_id=principal.client_id,
        permissions=sorted(principal.permissions),
        tenants=sorted(principal.tenants),
        all_tenants=principal.all_tenants,
        default_tenant=next(iter(principal.tenants)) if len(principal.tenants) == 1 else None,
    )
