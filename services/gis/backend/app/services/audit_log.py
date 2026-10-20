"""Reading the audit log: a tenant's entries, newest first, with keyset paging.

Row-level security decides what is visible: the entries of the transaction's tenant, or - for a platform
role acting for no tenant - the entries without one (reference data releases, searches of services that
act for no tenant). Reading the log is itself recorded.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import Access
from app.core.paging import InvalidCursorError, build_page, cursor_of, fetch_limit, query_fingerprint
from app.db.session import access_transaction
from app.repositories.audit import AuditEntryRow, AuditLogQuery, AuditRecord, AuditRepository
from app.schemas.audit import AuditActorOut, AuditEntryOut, AuditLogOut
from app.schemas.audit import AuditLogQuery as AuditLogParams


def _key(row: AuditEntryRow) -> dict[str, str]:
    return {"t": row.occurred_at.isoformat(), "i": str(row.id)}


class AuditLogService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def entries(self, access: Access, params: AuditLogParams) -> AuditLogOut:
        fingerprint = query_fingerprint(
            "audit",
            None if access.tenant is None else access.tenant.value,
            params.category,
            params.operation,
            params.actor_subject,
            params.time_from,
            params.time_to,
        )
        cursor = cursor_of(params.cursor, fingerprint=fingerprint)
        before_id: int | None = None
        if cursor is not None:
            try:
                before_id = int(cursor.text("i"))
            except ValueError as exc:
                raise InvalidCursorError("the cursor's 'i' must be an entry id") from exc
        async with access_transaction(self._session_factory, access) as session:
            repository = AuditRepository(session)
            rows = await repository.entries(
                AuditLogQuery(
                    limit=fetch_limit(params.limit),
                    time_from=params.time_from,
                    time_to=params.time_to,
                    category=params.category,
                    operation=params.operation,
                    actor_subject=params.actor_subject,
                    before_occurred_at=None if cursor is None else cursor.instant("t"),
                    before_id=before_id,
                )
            )
            page = build_page(rows, limit=params.limit, fingerprint=fingerprint, key_of=_key)
            await repository.record(
                AuditRecord(
                    category="sensitive_query",
                    operation="audit.list",
                    target="audit.entry",
                    parameters={
                        "category": params.category,
                        "operation": params.operation,
                        "actorSubject": params.actor_subject,
                        "from": params.time_from,
                        "to": params.time_to,
                        "limit": params.limit,
                        "continued": cursor is not None or None,
                    },
                    result_count=page.count,
                )
            )
        return AuditLogOut(
            items=[_entry_out(row) for row in page.items], count=page.count, next_cursor=page.next_cursor
        )


def _entry_out(row: AuditEntryRow) -> AuditEntryOut:
    return AuditEntryOut(
        id=row.id,
        occurred_at=row.occurred_at,
        tenant_id=row.tenant_id,
        category=row.category,
        operation=row.operation,
        target=row.target,
        object_id=row.object_id,
        actor=AuditActorOut(subject=row.actor_subject, client_id=row.actor_client),
        cross_tenant=row.cross_tenant,
        channel=row.channel,
        request_id=row.request_id,
        db_user=row.db_user,
        geometry_type=row.geometry_type,
        geometry_extent=row.geometry_extent,
        parameters=row.parameters,
        result_count=row.result_count,
    )
