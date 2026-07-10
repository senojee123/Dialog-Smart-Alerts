"""
Async repository (Stage B1).

Drop-in async replacement for the old JSON `data_store`: same generic CRUD names
(get_all / get_by_id / create / update / delete / count / upsert) returning plain
dicts, **plus** bounded, indexed query helpers for the hot paths (ingestion, rule
confirmation, spatial, enrichment) so we never full-scan the event firehose.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, delete as sa_delete, func

from db import async_session
from models import MODELS, DetectionEvent, Incident, Notification, Device


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id(name: str) -> str:
    return f"{name.upper()[:3]}-{uuid.uuid4().hex[:6].upper()}"


def _model(name: str):
    m = MODELS.get(name)
    if not m:
        raise KeyError(f"Unknown collection '{name}'")
    return m


def _project(model, data: dict) -> dict:
    """Mirrored column values pulled from the record dict."""
    return {col: data.get(col) for col in model.MIRROR}


# ── generic CRUD ──────────────────────────────────────────────────────────────

async def get_all(name: str) -> list[dict]:
    M = _model(name)
    async with async_session() as s:
        rows = (await s.execute(select(M.data))).scalars().all()
        return list(rows)


async def get_by_id(name: str, id: str) -> dict | None:
    M = _model(name)
    async with async_session() as s:
        row = await s.get(M, id)
        return row.data if row else None


async def create(name: str, data: dict) -> dict:
    M = _model(name)
    record = {
        **data,
        "id": data.get("id") or _gen_id(name),
        "created_at": data.get("created_at") or _now(),
        "updated_at": _now(),
    }
    async with async_session() as s:
        s.add(M(id=record["id"], data=record, **_project(M, record)))
        await s.commit()
    return record


async def update(name: str, id: str, patch: dict) -> dict | None:
    M = _model(name)
    async with async_session() as s:
        row = await s.get(M, id)
        if not row:
            return None
        merged = {**row.data, **patch, "updated_at": _now()}
        row.data = merged
        for col in M.MIRROR:
            setattr(row, col, merged.get(col))
        await s.commit()
        return merged


async def delete(name: str, id: str) -> bool:
    M = _model(name)
    async with async_session() as s:
        res = await s.execute(sa_delete(M).where(M.id == id))
        await s.commit()
        return res.rowcount > 0


async def count(name: str) -> int:
    M = _model(name)
    async with async_session() as s:
        return (await s.execute(select(func.count()).select_from(M))).scalar_one()


async def upsert(name: str, data: dict) -> dict:
    existing = await get_by_id(name, data.get("id", ""))
    if existing:
        return await update(name, data["id"], data)
    return await create(name, data)


# ── bounded / indexed helpers (the scale-critical paths) ──────────────────────

async def recent(name: str, limit: int = 200, order_key: str = "received_at") -> list[dict]:
    """Most-recent N records, ordered by an indexed string-timestamp column."""
    M = _model(name)
    col = getattr(M, order_key, None)
    async with async_session() as s:
        q = select(M.data)
        if col is not None:
            q = q.order_by(col.desc())
        q = q.limit(limit)
        return list((await s.execute(q)).scalars().all())


async def recent_matching_events(use_case_id: str, zone_id: str | None,
                                 cutoff_iso: str, same_zone: bool) -> list[dict]:
    """Events for a use case since `cutoff_iso` (for rule-confirmation windows)."""
    async with async_session() as s:
        q = select(DetectionEvent.data).where(
            DetectionEvent.use_case_id == use_case_id,
            DetectionEvent.received_at >= cutoff_iso,
        )
        if same_zone and zone_id is not None:
            q = q.where(DetectionEvent.zone_id == zone_id)
        return list((await s.execute(q)).scalars().all())


async def events_for_spatial(cutoff_iso: str) -> list[dict]:
    """Recent located events only — bounds the spatial recompute."""
    async with async_session() as s:
        q = select(DetectionEvent.data).where(
            DetectionEvent.received_at >= cutoff_iso,
            DetectionEvent.lat.isnot(None),
        )
        return list((await s.execute(q)).scalars().all())


async def open_incidents(use_case_id: str, zone_id: str) -> list[dict]:
    async with async_session() as s:
        q = select(Incident.data).where(
            Incident.use_case_id == use_case_id,
            Incident.zone_id == zone_id,
            Incident.status.in_(["ACTIVE", "OPERATOR_REVIEW"]),
        ).order_by(Incident.opened_at.desc())
        return list((await s.execute(q)).scalars().all())


async def closed_incident_event_ids(cutoff_iso: str) -> set[str]:
    """Event ids consumed by recently-closed incidents (confirmation scoping)."""
    async with async_session() as s:
        q = select(Incident.data).where(
            Incident.status.in_(["CLOSED", "RESOLVED"]),
            Incident.opened_at >= cutoff_iso,
        )
        rows = (await s.execute(q)).scalars().all()
    ids: set[str] = set()
    for inc in rows:
        ids.update(inc.get("event_ids", []))
    return ids


async def active_rules_for(use_case_id: str) -> list[dict]:
    async with async_session() as s:
        q = select(MODELS["rules"].data).where(
            MODELS["rules"].use_case_id == use_case_id,
            MODELS["rules"].active.is_(True),
        ).order_by(MODELS["rules"].priority.desc())
        return list((await s.execute(q)).scalars().all())


async def notifications_for_incident(incident_id: str) -> list[dict]:
    async with async_session() as s:
        q = select(Notification.data).where(Notification.incident_id == incident_id)
        return list((await s.execute(q)).scalars().all())


async def event_by_client_id(client_event_id: str) -> dict | None:
    async with async_session() as s:
        q = select(DetectionEvent.data).where(DetectionEvent.client_event_id == client_event_id).limit(1)
        return (await s.execute(q)).scalars().first()


async def device_by_external_id(external_id: str) -> dict | None:
    async with async_session() as s:
        q = select(Device.data).where(Device.external_id == external_id).limit(1)
        return (await s.execute(q)).scalars().first()


async def events_by_ids(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    async with async_session() as s:
        q = select(DetectionEvent.data).where(DetectionEvent.id.in_(list(ids)))
        return list((await s.execute(q)).scalars().all())


async def incident_for_event(event_id: str) -> dict | None:
    """Find the incident that consumed a given event (idempotency return path)."""
    async with async_session() as s:
        rows = (await s.execute(select(Incident.data))).scalars().all()
    return next((i for i in rows if event_id in (i.get("event_ids") or [])), None)
