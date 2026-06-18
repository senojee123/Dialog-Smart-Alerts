import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


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
        encoding="utf-8"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
