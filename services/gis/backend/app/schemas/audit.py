"""Requests and responses of the audit log and identity endpoints."""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import AwareDatetime, Field

from app.core.access import Permission
from app.schemas.base import ApiModel
from app.schemas.spatial_query import cursor_field, limit_field, tenant_field

AuditCategoryName = Literal["search", "sensitive_query", "export", "change", "release"]
OPERATION_PATTERN: Final = r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$"


class AuditLogQuery(ApiModel):
    """Query parameters of ``GET /geo/v1/audit/entries``."""

    category: AuditCategoryName | None = Field(default=None, description="Only entries of this category.")
    operation: str | None = Field(
        default=None,
        max_length=100,
        pattern=OPERATION_PATTERN,
        description="Only entries of this operation.",
        examples=["geofence.archive"],
    )
    actor_subject: str | None = Field(
        default=None, max_length=255, description="Only entries of this caller (subject id)."
    )
    time_from: AwareDatetime | None = Field(default=None, alias="from", description="Start (inclusive).")
    time_to: AwareDatetime | None = Field(default=None, alias="to", description="End (exclusive).")
    tenant_id: str | None = tenant_field()
    limit: int = limit_field()
    cursor: str | None = cursor_field()


class AuditActorOut(ApiModel):
    subject: str = Field(description="Who acted: `platform` for requests from the main platform.")
    client_id: str | None = Field(description="Client the caller used, if any.")


class AuditEntryOut(ApiModel):
    id: int
    occurred_at: AwareDatetime
    tenant_id: str | None = Field(description="Tenant the operation acted for.")
    category: AuditCategoryName
    operation: str = Field(examples=["query.within_distance"])
    target: str | None = Field(description="Layer or table read or changed.")
    object_id: str | None
    actor: AuditActorOut
    cross_tenant: bool = Field(description="The caller acted for a tenant not its own.")
    channel: Literal["api", "loader", "database"]
    request_id: str | None
    db_user: str = Field(description="Database login that wrote the entry.")
    geometry_type: str | None
    geometry_extent: dict[str, Any] | None = Field(
        description="Coarse extent of the geometry involved (GeoJSON polygon on a 0.001 degree grid)."
    )
    parameters: dict[str, Any]
    result_count: int | None


class AuditLogOut(ApiModel):
    items: list[AuditEntryOut]
    count: int
    next_cursor: str | None


class IdentityOut(ApiModel):
    """The caller as the GIS service sees it: what a client needs to decide what to offer."""

    subject: str
    client_id: str | None
    permissions: list[Permission] = Field(description="What the caller may do.")
    tenants: list[str] = Field(description="Tenants the request acts for.")
    all_tenants: bool = Field(description="May act for any registered tenant by naming it.")
    default_tenant: str | None = Field(
        description="Tenant used when a request names none: the caller's only tenant, else null."
    )
