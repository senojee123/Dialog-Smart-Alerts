"""Dependency injection.

Long-lived resources (settings, engine, session factory, services) are created once in the
application lifespan and stored in :class:`AppContainer`. Route handlers receive them through the
typed ``Annotated`` aliases below, which keeps handlers free of globals and easy to override in tests
(``app.dependency_overrides``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.access import Access, Actor
from app.core.caller import TENANT_HEADER, Principal, platform_caller
from app.core.config import Settings
from app.core.logging import request_id_var
from app.core.tenancy import TENANT_ID_PATTERN, TenantId
from app.db.session import transaction
from app.services.audit_log import AuditLogService
from app.services.enrichment import GeoContextService
from app.services.operational import OperationalService
from app.services.readiness import ReadinessService
from app.services.release_catalogue import ReleaseCatalogue
from app.services.spatial_query import SpatialQueryService
from app.spatial.service_area import ServiceArea


@dataclass(frozen=True, slots=True)
class AppContainer:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    service_area: ServiceArea
    readiness: ReadinessService
    geo_context: GeoContextService
    spatial_query: SpatialQueryService
    operational: OperationalService
    audit_log: AuditLogService
    releases: ReleaseCatalogue


def get_container(request: Request) -> AppContainer:
    container: AppContainer = request.app.state.container
    return container


Container = Annotated[AppContainer, Depends(get_container)]


def get_settings_dep(container: Container) -> Settings:
    return container.settings


def get_service_area(container: Container) -> ServiceArea:
    return container.service_area


def get_readiness_service(container: Container) -> ReadinessService:
    return container.readiness


def get_geo_context_service(container: Container) -> GeoContextService:
    return container.geo_context


async def get_db_session(container: Container) -> AsyncIterator[AsyncSession]:
    """One transaction without a tenant (reference data only; tenant data goes through services)."""
    async with transaction(container.session_factory) as session:
        yield session


async def get_principal(
    container: Container,
    tenant: Annotated[
        str | None,
        Header(
            alias=TENANT_HEADER,
            pattern=TENANT_ID_PATTERN,
            description="Tenant (organisation) the request acts for. Optional: without it the request acts "
            "for the platform's organisation (`GIS_TENANT_ID`). The main platform owns sign-in; the GIS "
            "checks no credentials.",
            examples=["dialog-smart-alerts"],
        ),
    ] = None,
) -> Principal:
    """The caller: the main platform, acting for one tenant (see :mod:`app.core.caller`)."""
    return platform_caller(tenant or container.settings.tenant_id)


def get_spatial_query_service(container: Container) -> SpatialQueryService:
    return container.spatial_query


def get_operational_service(container: Container) -> OperationalService:
    return container.operational


def get_release_catalogue(container: Container) -> ReleaseCatalogue:
    return container.releases


def get_audit_log_service(container: Container) -> AuditLogService:
    return container.audit_log


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ServiceAreaDep = Annotated[ServiceArea, Depends(get_service_area)]
ReadinessServiceDep = Annotated[ReadinessService, Depends(get_readiness_service)]
GeoContextServiceDep = Annotated[GeoContextService, Depends(get_geo_context_service)]
SpatialQueryServiceDep = Annotated[SpatialQueryService, Depends(get_spatial_query_service)]
OperationalServiceDep = Annotated[OperationalService, Depends(get_operational_service)]
AuditLogServiceDep = Annotated[AuditLogService, Depends(get_audit_log_service)]
ReleaseCatalogueDep = Annotated[ReleaseCatalogue, Depends(get_release_catalogue)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]

TENANT_PARAMETER = Query(
    alias="tenantId",
    pattern=TENANT_ID_PATTERN,
    description="Tenant whose data this request concerns: the one the request acts for (the "
    "`X-GIS-Tenant-Id` header, else the platform's organisation). It may be omitted.",
    examples=["wildlife-dept"],
)


def tenant_of(principal: Principal, tenant_id: str | None) -> TenantId | None:
    """The tenant to act for: the one asked for (if the caller acts for it), or the caller's only one."""
    if tenant_id is not None:
        return principal.require_tenant(tenant_id)
    if len(principal.tenants) == 1:
        return TenantId(next(iter(principal.tenants)))
    return None


def access_for(principal: Principal, tenant_id: str | None) -> Access:
    """The caller and the tenant it acts for (see :func:`tenant_of`)."""
    tenant = tenant_of(principal, tenant_id)
    return Access(
        actor=Actor(
            subject=principal.subject, client_id=principal.client_id, request_id=request_id_var.get()
        ),
        tenant=tenant,
        cross_tenant=tenant is not None and tenant.value not in principal.tenants,
    )


# The dependency form, for endpoints that take no Pydantic query model. Endpoints that do carry tenantId
# in that model and call access_for: FastAPI expands a query model into its fields only while it is the
# sole source of query parameters for the operation.
async def get_access(
    principal: PrincipalDep, tenant_id: Annotated[str | None, TENANT_PARAMETER] = None
) -> Access:
    return access_for(principal, tenant_id)


AccessDep = Annotated[Access, Depends(get_access)]
