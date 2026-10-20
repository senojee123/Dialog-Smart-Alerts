"""Exception handlers producing RFC 9457 problem details.

Unhandled exceptions are answered by ``RequestContextMiddleware`` so the response still carries the
request ID.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import GisError
from app.core.logging import request_id_var
from app.schemas.problem import PROBLEM_CONTENT_TYPE, PROBLEM_TYPE_PREFIX, ProblemDetail

logger = logging.getLogger(__name__)


# Standard members (RFC 9457 plus requestId); extensions never replace them.
_RESERVED_MEMBERS = frozenset({"type", "title", "status", "detail", "instance", "requestId"})


def _problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None,
    extensions: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    members = {key: value for key, value in (extensions or {}).items() if key not in _RESERVED_MEMBERS}
    if len(members) != len(extensions or {}):
        logger.warning("problem extensions dropped: %s", sorted(set(extensions or {}) - set(members)))
    problem = ProblemDetail(
        type=f"{PROBLEM_TYPE_PREFIX}{code}",
        title=title,
        status=status,
        detail=detail,
        instance=request.url.path,
        requestId=request_id_var.get(),
        **members,
    )
    return JSONResponse(
        problem.to_body(), status_code=status, media_type=PROBLEM_CONTENT_TYPE, headers=headers
    )


async def _gis_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GisError)
    if exc.status_code >= 500:
        logger.error("request failed: %s", exc.detail, extra={"error_code": exc.code})
    return _problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        extensions=exc.extensions,
        headers=exc.headers,
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return _problem_response(
        request,
        status=422,
        code="request_validation_error",
        title="Request failed validation",
        detail="one or more request fields are invalid",
        extensions={"errors": errors},
    )


# Problem codes for HTTP errors raised by the framework or middleware (default: http_<status>).
_HTTP_ERROR_CODES = {413: "payload_too_large"}


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return _problem_response(
        request,
        status=exc.status_code,
        code=_HTTP_ERROR_CODES.get(exc.status_code, f"http_{exc.status_code}"),
        title=str(exc.detail) if exc.detail else "HTTP error",
        detail=None,
        headers=getattr(exc, "headers", None),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(GisError, _gis_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
