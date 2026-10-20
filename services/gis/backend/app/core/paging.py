"""Keyset (cursor) pagination.

Collections are read in a deterministic order and paged by remembering the last row's ordering key,
never by an offset: with an offset, rows inserted or changed between two pages are skipped or repeated,
and deep pages get progressively slower. The cursor is opaque - clients pass ``nextCursor`` back
unchanged - and carries

* the ordering key of the last row of the previous page (a few JSON scalars), and
* a fingerprint of the query it belongs to.

The fingerprint makes a cursor usable only with the query that produced it: a cursor sent with different
filters, a different layer or a different release is rejected instead of silently answering from another
result set. It is a hash of the query parameters, not a signature; the cursor is not a capability and
grants nothing. Its values only ever reach SQL as bound parameters, and every part is type-checked on
the way in.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from app.core.errors import GisValidationError

DEFAULT_LIMIT: Final = 100
MAX_LIMIT: Final = 1000
MAX_CURSOR_CHARS: Final = 512
_FINGERPRINT_CHARS: Final = 16

Scalar = str | int | float | bool | None


class InvalidCursorError(GisValidationError):
    code = "invalid_cursor"
    title = "Cursor is not acceptable"


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, frozenset | set):
        return sorted(str(item) for item in value)
    if isinstance(value, bytes):
        # Geometries shape a result set, so they belong in the fingerprint - by their digest, not verbatim.
        return hashlib.sha256(value).hexdigest()
    raise TypeError(f"cannot put {type(value).__name__} in a cursor")


def _canonical(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=_json_default)


def query_fingerprint(*parts: Any) -> str:
    """Stable short hash of everything that shapes a result set (layer, filters, order, release)."""
    digest = hashlib.sha256(_canonical(parts).encode("utf-8")).hexdigest()
    return digest[:_FINGERPRINT_CHARS]


def encode_cursor(values: Mapping[str, Any], *, fingerprint: str) -> str:
    payload = _canonical({"k": fingerprint, "v": dict(values)}).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


@dataclass(frozen=True, slots=True)
class CursorValues:
    """The decoded ordering key. Each accessor checks the type, so a hand-made cursor cannot smuggle
    an unexpected value into a parameter."""

    values: Mapping[str, Scalar]

    def _raw(self, key: str) -> Scalar:
        if key not in self.values:
            raise InvalidCursorError(f"the cursor does not contain {key!r}", extensions={"cursorKey": key})
        return self.values[key]

    def text(self, key: str) -> str:
        value = self._raw(key)
        if not isinstance(value, str):
            raise InvalidCursorError(f"the cursor's {key!r} must be a string")
        return value

    def number(self, key: str) -> float:
        value = self._raw(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise InvalidCursorError(f"the cursor's {key!r} must be a number")
        # JSON allows Infinity and NaN; as a keyset bound either would restart or empty the page.
        if not math.isfinite(value):
            raise InvalidCursorError(f"the cursor's {key!r} must be a finite number")
        return float(value)

    def identifier(self, key: str) -> uuid.UUID:
        try:
            return uuid.UUID(self.text(key))
        except ValueError as exc:
            raise InvalidCursorError(f"the cursor's {key!r} must be a UUID") from exc

    def instant(self, key: str) -> datetime:
        try:
            moment = datetime.fromisoformat(self.text(key))
        except ValueError as exc:
            raise InvalidCursorError(f"the cursor's {key!r} must be an ISO 8601 timestamp") from exc
        if moment.tzinfo is None:
            raise InvalidCursorError(f"the cursor's {key!r} must carry a UTC offset")
        return moment


def decode_cursor(cursor: str, *, fingerprint: str) -> CursorValues:
    """Decode a cursor produced by :func:`encode_cursor` for the same query, or raise 422."""
    if len(cursor) > MAX_CURSOR_CHARS:
        raise InvalidCursorError(f"the cursor is longer than {MAX_CURSOR_CHARS} characters")
    padding = "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError("the cursor is malformed; pass nextCursor back unchanged") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("v"), dict):
        raise InvalidCursorError("the cursor is malformed; pass nextCursor back unchanged")
    if payload.get("k") != fingerprint:
        raise InvalidCursorError(
            "the cursor belongs to a different query; page through a result set with unchanged parameters"
        )
    values = payload["v"]
    if not all(isinstance(key, str) and isinstance(value, Scalar) for key, value in values.items()):
        raise InvalidCursorError("the cursor is malformed; pass nextCursor back unchanged")
    return CursorValues(values)


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of results and the cursor for the next one (``None`` on the last page)."""

    items: tuple[T, ...]
    next_cursor: str | None

    @property
    def count(self) -> int:
        return len(self.items)


def build_page[T](
    rows: Sequence[T], *, limit: int, fingerprint: str, key_of: Callable[[T], Mapping[str, Any]]
) -> Page[T]:
    """Turn ``limit + 1`` fetched rows into a page of at most ``limit`` items plus a cursor.

    Repositories fetch one row more than requested; its existence is what tells the page there is more.
    """
    items = tuple(rows[:limit])
    if len(rows) <= limit or not items:
        return Page(items=items, next_cursor=None)
    return Page(items=items, next_cursor=encode_cursor(key_of(items[-1]), fingerprint=fingerprint))


def fetch_limit(limit: int) -> int:
    return limit + 1


def cursor_of(cursor: str | None, *, fingerprint: str) -> CursorValues | None:
    return None if cursor is None else decode_cursor(cursor, fingerprint=fingerprint)
