"""Structured logging.

Every log line is a single JSON object (or a readable line with ``GIS_LOG_FORMAT=console``) that
carries the current request ID. Extra fields passed through ``logger.info(..., extra={...})`` are
emitted as top-level keys.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

from app.core.config import LogFormat

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes present on every LogRecord; anything else was supplied through ``extra``.
# ``color_message`` is uvicorn's ANSI-coloured duplicate of the message.
_RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "color_message",
}


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {key: value for key, value in record.__dict__.items() if key not in _RESERVED}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:-3]
        request_id = request_id_var.get()
        extras = _extra_fields(record)
        parts = [f"{timestamp} {record.levelname:<7} {record.name}: {record.getMessage()}"]
        if request_id is not None:
            parts.append(f"request_id={request_id}")
        parts.extend(f"{key}={value}" for key, value in extras.items())
        line = " ".join(parts)
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(level: str, fmt: LogFormat, *, stream: TextIO | None = None) -> None:
    """Route all application and server logs through one handler (stdout; command-line tools pass stderr)."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt is LogFormat.JSON else ConsoleFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Uvicorn installs its own handlers; send its records to the root handler instead.
    for name in ("uvicorn", "uvicorn.error"):
        server_logger = logging.getLogger(name)
        server_logger.handlers = []
        server_logger.propagate = True
    # Access logging is done by RequestContextMiddleware (with request IDs and durations).
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = []
    access_logger.propagate = False
    access_logger.disabled = True
    # SQLAlchemy engine logging is very verbose at INFO; keep it at WARNING unless debugging.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING if level != "DEBUG" else logging.INFO)
