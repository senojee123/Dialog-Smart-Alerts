"""Request context middleware: request IDs, access logging and HTTP metrics.

Implemented as plain ASGI middleware (not ``BaseHTTPMiddleware``) so it adds no buffering and works
for streaming responses.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import TYPE_CHECKING

from fastapi import HTTPException
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    gc_collector,
    platform_collector,
    process_collector,
)
from starlette.datastructures import MutableHeaders

from app.core.logging import request_id_var
from app.schemas.problem import PROBLEM_CONTENT_TYPE, PROBLEM_TYPE_PREFIX

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
UNMATCHED_ROUTE = "<unmatched>"

access_logger = logging.getLogger("app.access")
logger = logging.getLogger(__name__)


async def _send_problem(
    send: Send, scope: Scope, *, status: int, code: str, title: str, detail: str, **extensions: object
) -> None:
    body = json.dumps(
        {
            "type": f"{PROBLEM_TYPE_PREFIX}{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": scope.get("path", ""),
            "requestId": request_id_var.get(),
            **extensions,
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", PROBLEM_CONTENT_TYPE.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _send_internal_error(send: Send, scope: Scope) -> None:
    await _send_problem(
        send,
        scope,
        status=500,
        code="internal_error",
        title="Internal server error",
        detail="an unexpected error occurred; quote the request ID when reporting it",
    )


PAYLOAD_TOO_LARGE_TITLE = "Request body too large"


class BodySizeLimitMiddleware:
    """Reject request bodies above ``max_bytes`` with 413, before they are buffered or parsed.

    A declared ``Content-Length`` is checked up front; chunked bodies are counted while they are read
    (the error then surfaces through FastAPI, which re-raises HTTP exceptions from body reading).
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared < 0 or declared > self.max_bytes:
                    await _send_problem(
                        send,
                        scope,
                        status=413,
                        code="payload_too_large",
                        title=PAYLOAD_TOO_LARGE_TITLE,
                        detail=f"the request body must not exceed {self.max_bytes} bytes",
                        maxBytes=self.max_bytes,
                    )
                    return
        received = 0
        limit = self.max_bytes

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=413, detail=PAYLOAD_TOO_LARGE_TITLE)
            return message

        await self.app(scope, limited_receive, send)


class HttpMetrics:
    """Prometheus metrics held in a per-application registry (safe for multiple app instances)."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        process_collector.ProcessCollector(registry=self.registry)
        platform_collector.PlatformCollector(registry=self.registry)
        gc_collector.GCCollector(registry=self.registry)
        self.requests = Counter(
            "gis_http_requests_total",
            "HTTP requests handled, by route template and status code.",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "gis_http_request_duration_seconds",
            "HTTP request latency by route template.",
            ["method", "route"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.3, 0.5, 0.8, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )


def _incoming_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            return candidate if _VALID_REQUEST_ID.fullmatch(candidate) else None
    return None


def _route_template(scope: Scope) -> str:
    # FastAPI stores the matched APIRoute in the scope; use its template to keep label cardinality low.
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else UNMATCHED_ROUTE


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, metrics: HttpMetrics | None) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_started = True
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Unhandled errors: log once with the request ID and answer with a problem document,
            # without exposing internals. If the response already started, the connection is lost anyway.
            logger.exception("unhandled error while processing request")
            if response_started:
                raise
            await _send_internal_error(send_with_request_id, scope)
        finally:
            duration = time.perf_counter() - started
            route = _route_template(scope)
            method = scope.get("method", "")
            if self.metrics is not None:
                self.metrics.requests.labels(method, route, str(status_code)).inc()
                self.metrics.latency.labels(method, route).observe(duration)
            access_logger.info(
                "request completed",
                extra={
                    "http_method": method,
                    "http_path": scope.get("path", ""),
                    "http_route": route,
                    "http_status": status_code,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            request_id_var.reset(token)
