"""Keyset paging: cursors are opaque, typed on the way in, and tied to the query that made them."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.core.paging import (
    DEFAULT_LIMIT,
    MAX_CURSOR_CHARS,
    MAX_LIMIT,
    InvalidCursorError,
    build_page,
    cursor_of,
    decode_cursor,
    encode_cursor,
    fetch_limit,
    query_fingerprint,
)


@dataclass(frozen=True, slots=True)
class Row:
    id: uuid.UUID
    distance_m: float


def _key(row: Row) -> dict[str, Any]:
    return {"id": str(row.id), "d": row.distance_m}


def _rows(count: int) -> list[Row]:
    return [Row(id=uuid.UUID(int=index, version=4), distance_m=float(index)) for index in range(count)]


def test_a_cursor_round_trips_its_ordering_key() -> None:
    fingerprint = query_fingerprint("features", "ref.settlement", {"type": "town"})
    moment = datetime(2026, 9, 10, 4, 30, tzinfo=UTC)
    identifier = uuid.uuid4()
    cursor = encode_cursor(
        {"id": str(identifier), "d": 12.5, "t": moment.isoformat()}, fingerprint=fingerprint
    )

    values = decode_cursor(cursor, fingerprint=fingerprint)

    assert values.identifier("id") == identifier
    assert values.number("d") == 12.5
    assert values.instant("t") == moment
    assert values.text("id") == str(identifier)


def test_a_cursor_is_opaque_but_carries_no_secret() -> None:
    cursor = encode_cursor({"id": "abc"}, fingerprint="0123456789abcdef")

    assert "=" not in cursor  # url-safe, unpadded
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=="))
    assert payload == {"k": "0123456789abcdef", "v": {"id": "abc"}}


def test_a_cursor_from_another_query_is_refused() -> None:
    cursor = encode_cursor({"id": "abc"}, fingerprint=query_fingerprint("features", "ref.settlement"))

    with pytest.raises(InvalidCursorError) as info:
        decode_cursor(cursor, fingerprint=query_fingerprint("features", "ref.road"))

    assert "different query" in str(info.value)


@pytest.mark.parametrize(
    "cursor",
    ["not base64 !!", "", base64.urlsafe_b64encode(b"[]").decode(), base64.urlsafe_b64encode(b"{}").decode()],
)
def test_a_malformed_cursor_is_refused(cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor, fingerprint="0123456789abcdef")


def test_an_oversized_cursor_is_refused_before_it_is_decoded() -> None:
    with pytest.raises(InvalidCursorError, match=str(MAX_CURSOR_CHARS)):
        decode_cursor("A" * (MAX_CURSOR_CHARS + 1), fingerprint="0123456789abcdef")


def test_cursor_values_are_type_checked() -> None:
    fingerprint = "0123456789abcdef"
    values = decode_cursor(
        encode_cursor({"id": "not-a-uuid", "d": "12", "t": "2026-09-10T04:30:00"}, fingerprint=fingerprint),
        fingerprint=fingerprint,
    )

    with pytest.raises(InvalidCursorError, match="UUID"):
        values.identifier("id")
    with pytest.raises(InvalidCursorError, match="number"):
        values.number("d")
    with pytest.raises(InvalidCursorError, match="offset"):
        values.instant("t")
    with pytest.raises(InvalidCursorError, match="missing"):
        values.text("missing")


def test_a_cursor_cannot_smuggle_a_structure() -> None:
    fingerprint = "0123456789abcdef"
    payload = json.dumps({"k": fingerprint, "v": {"id": {"nested": True}}}).encode()
    cursor = base64.urlsafe_b64encode(payload).decode().rstrip("=")

    with pytest.raises(InvalidCursorError):
        decode_cursor(cursor, fingerprint=fingerprint)


def test_uuid_and_datetime_keys_may_be_passed_unconverted() -> None:
    fingerprint = "0123456789abcdef"
    identifier, moment = uuid.uuid4(), datetime(2026, 1, 1, tzinfo=UTC)

    values = decode_cursor(
        encode_cursor({"id": identifier, "t": moment, "d": Decimal("1.50")}, fingerprint=fingerprint),
        fingerprint=fingerprint,
    )

    assert values.identifier("id") == identifier
    assert values.instant("t") == moment
    assert values.number("d") == 1.5


def test_the_fingerprint_covers_the_geometry_without_carrying_it() -> None:
    one = query_fingerprint("within-distance", b"\x00\x01", 500.0)
    same = query_fingerprint("within-distance", b"\x00\x01", 500.0)
    other = query_fingerprint("within-distance", b"\x00\x02", 500.0)

    assert one == same != other
    assert len(one) == 16


def test_a_full_page_carries_a_cursor_for_the_next_one() -> None:
    fingerprint = "0123456789abcdef"
    rows = _rows(4)

    page = build_page(rows, limit=3, fingerprint=fingerprint, key_of=_key)

    assert page.count == 3
    assert page.items == tuple(rows[:3])
    assert page.next_cursor is not None
    values = decode_cursor(page.next_cursor, fingerprint=fingerprint)
    assert values.identifier("id") == rows[2].id
    assert values.number("d") == 2.0


@pytest.mark.parametrize("count", [0, 1, 3])
def test_the_last_page_has_no_cursor(count: int) -> None:
    page = build_page(_rows(count), limit=3, fingerprint="0123456789abcdef", key_of=_key)

    assert page.count == count
    assert page.next_cursor is None


def test_repositories_fetch_one_row_more_than_the_page() -> None:
    assert fetch_limit(DEFAULT_LIMIT) == DEFAULT_LIMIT + 1
    assert fetch_limit(MAX_LIMIT) == MAX_LIMIT + 1


def test_no_cursor_means_the_first_page() -> None:
    assert cursor_of(None, fingerprint="0123456789abcdef") is None
