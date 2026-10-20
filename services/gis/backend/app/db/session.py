"""Transactional sessions with tenant and actor context (ADR-09, ADR-0017, plan Section 9).

The context is written with ``set_config(..., is_local => true)``, the function form of ``SET LOCAL``.
The values live only until the transaction ends, so a pooled connection can never carry one request's
tenant or caller into the next request.

* ``gis.tenant_id`` - read by ``meta.current_tenant_id()`` in every row-level security policy;
* ``gis.actor_subject``, ``gis.actor_client``, ``gis.actor_roles``, ``gis.request_id``, ``gis.channel``,
  ``gis.cross_tenant`` - read by the audit log's stamping trigger (``audit.stamp_entry``), so an audit
  entry names the caller whether the API or a trigger on a changed row wrote it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import Access
from app.core.tenancy import TENANT_SETTING, TenantId

ACTOR_SETTINGS: Final = (
    "gis.actor_subject",
    "gis.actor_client",
    "gis.actor_roles",
    "gis.request_id",
    "gis.channel",
    "gis.cross_tenant",
)

_SET_TENANT = text("SELECT set_config(:setting, :tenant_id, true)")
# One round trip for the whole context. Setting names are constants; every value is a bound parameter.
_SET_ACCESS = text(
    "SELECT set_config('gis.tenant_id', :tenant_id, true), "
    "set_config('gis.actor_subject', :subject, true), "
    "set_config('gis.actor_client', :client, true), "
    "set_config('gis.actor_roles', :roles, true), "
    "set_config('gis.request_id', :request_id, true), "
    "set_config('gis.channel', :channel, true), "
    "set_config('gis.cross_tenant', :cross_tenant, true)"
)


@asynccontextmanager
async def transaction(
    session_factory: async_sessionmaker[AsyncSession],
    tenant: TenantId | None = None,
) -> AsyncIterator[AsyncSession]:
    """Open a session and a transaction; commit on success, roll back on any exception.

    For work no request carries (fixtures, maintenance). A request's work goes through
    :func:`access_transaction`, which also records who is acting.
    """
    async with session_factory() as session, session.begin():
        if tenant is not None:
            await session.execute(_SET_TENANT, {"setting": TENANT_SETTING, "tenant_id": tenant.value})
        yield session


@asynccontextmanager
async def access_transaction(
    session_factory: async_sessionmaker[AsyncSession], access: Access
) -> AsyncIterator[AsyncSession]:
    """A transaction acting for ``access``: its tenant for row-level security, its actor for the audit log."""
    actor = access.actor
    async with session_factory() as session, session.begin():
        await session.execute(
            _SET_ACCESS,
            {
                "tenant_id": "" if access.tenant is None else access.tenant.value,
                "subject": actor.subject,
                "client": actor.client_id or "",
                "roles": "",  # the GIS has no roles; the audit log records none
                "request_id": actor.request_id or "",
                "channel": actor.channel,
                "cross_tenant": "on" if access.cross_tenant else "off",
            },
        )
        yield session
