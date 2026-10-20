"""The audit log: writing entries in the caller's transaction, and reading a tenant's log.

Entries are written in the same transaction as the operation they describe. If the entry cannot be
written the transaction fails, so an answer is never given - and a change never committed - without its
record (fail closed).

The writer supplies *what* happened. *Who*, *when* and *for which tenant* are stamped by the database
from the transaction's context (``audit.stamp_entry``, migration 20260923_0007); an INSERT cannot set
them. Geometry is passed as WKB and kept only as its type and a coarse extent (``audit.coarse_extent``).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Literal

from sqlalchemy import ColumnElement, bindparam, cast, func, literal, select, text, tuple_
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEntry

AuditCategory = Literal["search", "sensitive_query", "export", "change", "release"]
AUDIT_CATEGORIES: Final[tuple[AuditCategory, ...]] = (
    "search",
    "sensitive_query",
    "export",
    "change",
    "release",
)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, frozenset | set | tuple):
        return sorted(str(item) for item in value)
    raise TypeError(f"cannot record {type(value).__name__} in an audit entry")


def _parameters(values: Mapping[str, Any]) -> dict[str, Any]:
    """JSON-safe parameters, without members that are unset."""
    document: dict[str, Any] = json.loads(json.dumps(dict(values), default=_json_default))
    return {key: value for key, value in document.items() if value is not None and value != {}}


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """What an operation did, as the API describes it."""

    category: AuditCategory
    operation: str
    target: str | None = None
    object_id: str | None = None
    geometry_wkb: bytes | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    result_count: int | None = None


_INSERT = text(
    """
    INSERT INTO audit.entry
        (category, operation, target, object_id, geometry_type, geometry_extent, parameters, result_count)
    SELECT :category, :operation, :target, :object_id,
           public.GeometryType(g.geom), audit.coarse_extent(g.geom), :parameters, :result_count
    FROM (SELECT public.ST_GeomFromWKB(:wkb, 4326) AS geom) AS g
    """
).bindparams(bindparam("wkb", type_=BYTEA), bindparam("parameters", type_=JSONB))


@dataclass(frozen=True, slots=True)
class AuditEntryRow:
    id: int
    occurred_at: datetime
    tenant_id: str | None
    category: str
    operation: str
    target: str | None
    object_id: str | None
    actor_subject: str
    actor_client: str | None
    actor_roles: tuple[str, ...]
    cross_tenant: bool
    channel: str
    request_id: str | None
    db_user: str
    geometry_type: str | None
    geometry_extent: dict[str, Any] | None
    parameters: dict[str, Any]
    result_count: int | None


@dataclass(frozen=True, slots=True)
class AuditLogQuery:
    limit: int
    time_from: datetime | None = None
    time_to: datetime | None = None
    category: str | None = None
    operation: str | None = None
    actor_subject: str | None = None
    # Keyset: newest first, so a later page continues strictly before this (occurred_at, id).
    before_occurred_at: datetime | None = None
    before_id: int | None = None


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, record: AuditRecord) -> None:
        await self._session.execute(
            _INSERT,
            {
                "category": record.category,
                "operation": record.operation,
                "target": record.target,
                "object_id": record.object_id,
                "wkb": record.geometry_wkb,
                "parameters": _parameters(record.parameters),
                "result_count": record.result_count,
            },
        )

    async def entries(self, query: AuditLogQuery) -> list[AuditEntryRow]:
        """The entries visible to this transaction (row-level security decides which), newest first."""
        entry = AuditEntry.__table__.c
        conditions: list[ColumnElement[bool]] = []
        if query.time_from is not None:
            conditions.append(entry.occurred_at >= query.time_from)
        if query.time_to is not None:
            conditions.append(entry.occurred_at < query.time_to)
        if query.category is not None:
            conditions.append(entry.category == query.category)
        if query.operation is not None:
            conditions.append(entry.operation == query.operation)
        if query.actor_subject is not None:
            conditions.append(entry.actor_subject == query.actor_subject)
        if query.before_occurred_at is not None and query.before_id is not None:
            conditions.append(
                tuple_(entry.occurred_at, entry.id)
                < tuple_(literal(query.before_occurred_at), literal(query.before_id))
            )
        statement = (
            select(
                *(column for column in AuditEntry.__table__.c if column.name != "geometry_extent"),
                cast(func.ST_AsGeoJSON(entry.geometry_extent), JSONB).label("extent"),
            )
            .where(*conditions)
            .order_by(entry.occurred_at.desc(), entry.id.desc())
            .limit(query.limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            AuditEntryRow(
                id=row.id,
                occurred_at=row.occurred_at,
                tenant_id=row.tenant_id,
                category=row.category,
                operation=row.operation,
                target=row.target,
                object_id=row.object_id,
                actor_subject=row.actor_subject,
                actor_client=row.actor_client,
                actor_roles=tuple(row.actor_roles),
                cross_tenant=row.cross_tenant,
                channel=row.channel,
                request_id=row.request_id,
                db_user=row.db_user,
                geometry_type=row.geometry_type,
                geometry_extent=row.extent,
                parameters=dict(row.parameters),
                result_count=row.result_count,
            )
            for row in rows
        ]
