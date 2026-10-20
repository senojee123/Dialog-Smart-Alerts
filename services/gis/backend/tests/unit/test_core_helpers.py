from __future__ import annotations

import json
import logging
import sys

import pytest

from app.core.config import LogFormat
from app.core.logging import ConsoleFormatter, JsonFormatter, configure_logging, request_id_var
from app.core.tenancy import TenantId


@pytest.mark.parametrize("value", ["tenant-a", "dwc_north", "3f2c9a4e-5a41-4c6e-9d6a-0f7f2d9d1c11"])
def test_valid_tenant_ids(value: str) -> None:
    assert str(TenantId(value)) == value


@pytest.mark.parametrize("value", ["", "a", "Tenant", "tenant a", "-tenant", "t" * 64, "x';--"])
def test_invalid_tenant_ids(value: str) -> None:
    with pytest.raises(ValueError, match="tenant id"):
        TenantId(value)


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_includes_request_id_and_extra_fields() -> None:
    token = request_id_var.set("req-123")
    try:
        line = JsonFormatter().format(_record("hello", http_status=200))
    finally:
        request_id_var.reset(token)
    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["request_id"] == "req-123"
    assert payload["http_status"] == 200
    assert payload["level"] == "INFO"
    assert payload["timestamp"].endswith("+00:00")


def test_json_formatter_includes_exceptions() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord("app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    payload = json.loads(JsonFormatter().format(record))
    assert "RuntimeError: boom" in payload["exception"]


def test_uvicorn_colour_duplicates_are_dropped() -> None:
    payload = json.loads(JsonFormatter().format(_record("started", color_message="\x1b[36mstarted\x1b[0m")))
    assert "color_message" not in payload


def test_console_formatter_is_single_line_without_exception() -> None:
    line = ConsoleFormatter().format(_record("hello", duration_ms=1.5))
    assert "hello" in line
    assert "duration_ms=1.5" in line
    assert "\n" not in line


def test_configure_logging_installs_one_root_handler_and_silences_uvicorn_access() -> None:
    configure_logging("INFO", LogFormat.JSON)
    configure_logging("INFO", LogFormat.JSON)
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert logging.getLogger("uvicorn.access").disabled
