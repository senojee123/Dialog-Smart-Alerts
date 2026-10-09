"""
data_store.py – document store backed by PostgreSQL (production) or JSON files (local dev).

The public API is identical regardless of backend:
    get_all / get_by_id / create / update / delete / upsert / count

Set DATABASE_URL to a postgresql:// connection string to enable PostgreSQL.
Without it the module falls back to the original JSON-file behaviour so local
development works with no extra setup.

PostgreSQL schema (one table, document-store style):
    store(collection TEXT, id TEXT, data JSONB)  PK (collection, id)
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DB_URL = os.getenv("DATABASE_URL", "")
_USE_PG = bool(_DB_URL) and _DB_URL.startswith(("postgresql", "postgres"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# PostgreSQL backend  (Railway production — DATABASE_URL is set)
# ══════════════════════════════════════════════════════════════════════════════
if _USE_PG:
    import psycopg2
    import psycopg2.pool
    import psycopg2.extras

    # Railway sometimes issues postgres:// (libpq dialect); psycopg2 needs postgresql://
    _dsn = _DB_URL.replace("postgres://", "postgresql://", 1)

    # ThreadedConnectionPool is safe to share across threads (MQTT thread + async workers).
    _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, _dsn)

    def _conn():
        return _pool.getconn()

    def _release(c):
        _pool.putconn(c)

    # Bootstrap the schema once at import time — idempotent, safe to run every startup.
    _c = _conn()
    try:
        with _c.cursor() as _cur:
            _cur.execute("""
                CREATE TABLE IF NOT EXISTS store (
                    collection  TEXT NOT NULL,
                    id          TEXT NOT NULL,
                    data        JSONB NOT NULL,
                    PRIMARY KEY (collection, id)
                )
            """)
            _cur.execute(
                "CREATE INDEX IF NOT EXISTS store_coll_idx ON store (collection)"
            )
        _c.commit()
        print("[DATA_STORE] PostgreSQL backend ready.")
    finally:
        _release(_c)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def get_all(name: str) -> list:
        c = _conn()
        try:
            with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT data FROM store WHERE collection = %s", (name,)
                )
                return [row["data"] for row in cur.fetchall()]
        finally:
            _release(c)

    def get_by_id(name: str, id: str) -> dict | None:
        c = _conn()
        try:
            with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT data FROM store WHERE collection = %s AND id = %s",
                    (name, id),
                )
                row = cur.fetchone()
                return dict(row["data"]) if row else None
        finally:
            _release(c)

    def create(name: str, data: dict) -> dict:
        data = {
            **data,
            "id": data.get("id") or f"{name.upper()[:3]}-{uuid.uuid4().hex[:6].upper()}",
            "created_at": _now(),
            "updated_at": _now(),
        }
        c = _conn()
        try:
            with c.cursor() as cur:
                cur.execute(
                    "INSERT INTO store (collection, id, data) VALUES (%s, %s, %s)",
                    (name, data["id"], psycopg2.extras.Json(data)),
                )
            c.commit()
        finally:
            _release(c)
        return data

    def update(name: str, id: str, patch: dict) -> dict | None:
        c = _conn()
        try:
            with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT data FROM store WHERE collection = %s AND id = %s FOR UPDATE",
                    (name, id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                updated = {**row["data"], **patch, "updated_at": _now()}
                cur.execute(
                    "UPDATE store SET data = %s WHERE collection = %s AND id = %s",
                    (psycopg2.extras.Json(updated), name, id),
                )
            c.commit()
            return updated
        finally:
            _release(c)

    def delete(name: str, id: str) -> bool:
        c = _conn()
        try:
            with c.cursor() as cur:
                cur.execute(
                    "DELETE FROM store WHERE collection = %s AND id = %s",
                    (name, id),
                )
                deleted = cur.rowcount > 0
            c.commit()
            return deleted
        finally:
            _release(c)

    def upsert(name: str, data: dict) -> dict:
        existing = get_by_id(name, data.get("id", ""))
        if existing:
            return update(name, data["id"], data)
        return create(name, data)

    def count(name: str) -> int:
        c = _conn()
        try:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM store WHERE collection = %s", (name,)
                )
                return cur.fetchone()[0]
        finally:
            _release(c)


# ══════════════════════════════════════════════════════════════════════════════
# JSON-file fallback  (local dev — no DATABASE_URL set)
# ══════════════════════════════════════════════════════════════════════════════
else:
    DATA_DIR = Path(__file__).parent / "data"
    DATA_DIR.mkdir(exist_ok=True)

    print("[DATA_STORE] No DATABASE_URL — using local JSON-file store.")

    def _path(name: str) -> Path:
        return DATA_DIR / f"{name}.json"

    def _load(name: str) -> list:
        p = _path(name)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(name: str, items: list):
        _path(name).write_text(
            json.dumps(items, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_all(name: str) -> list:
        return _load(name)

    def get_by_id(name: str, id: str) -> dict | None:
        return next((x for x in _load(name) if x.get("id") == id), None)

    def create(name: str, data: dict) -> dict:
        items = _load(name)
        prefix = name.upper()[:3]
        data = {
            **data,
            "id": data.get("id") or f"{prefix}-{uuid.uuid4().hex[:6].upper()}",
            "created_at": _now(),
            "updated_at": _now(),
        }
        items.append(data)
        _save(name, items)
        return data

    def update(name: str, id: str, patch: dict) -> dict | None:
        items = _load(name)
        for i, item in enumerate(items):
            if item.get("id") == id:
                items[i] = {**item, **patch, "updated_at": _now()}
                _save(name, items)
                return items[i]
        return None

    def delete(name: str, id: str) -> bool:
        items = _load(name)
        new_items = [x for x in items if x.get("id") != id]
        if len(new_items) == len(items):
            return False
        _save(name, new_items)
        return True

    def upsert(name: str, data: dict) -> dict:
        existing = get_by_id(name, data.get("id", ""))
        if existing:
            return update(name, data["id"], data)
        return create(name, data)

    def count(name: str) -> int:
        return len(_load(name))
