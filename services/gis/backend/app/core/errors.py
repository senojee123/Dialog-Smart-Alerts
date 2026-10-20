"""Domain exceptions.

API handlers translate these into RFC 9457 problem details (``application/problem+json``). The
``code`` becomes part of the problem ``type`` URI so clients can branch on it reliably.
"""

from __future__ import annotations

from typing import Any, ClassVar


class GisError(Exception):
    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "internal_error"
    title: ClassVar[str] = "Internal server error"

    def __init__(
        self,
        detail: str,
        *,
        extensions: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extensions = extensions or {}
        self.headers = headers


class BadRequestError(GisError):
    """The request itself cannot be processed (as opposed to its content being invalid)."""

    status_code = 400
    code = "bad_request"
    title = "Request cannot be processed"


class TenantRequiredError(BadRequestError):
    """The operation reads or writes tenant data, but the request does not say which tenant."""

    code = "tenant_required"
    title = "Tenant must be given"


class GisValidationError(GisError):
    status_code = 422
    code = "validation_error"
    title = "Request failed validation"


class UnsupportedFilterError(GisValidationError):
    """A filter that does not apply here. Filters are rejected rather than ignored, so a typo cannot
    silently widen a result set."""

    code = "unsupported_filter"
    title = "Filter is not supported here"


class CoordinateError(GisValidationError):
    code = "invalid_coordinate"
    title = "Coordinate is not acceptable"


class InvalidGeometryError(GisValidationError):
    code = "invalid_geometry"
    title = "Geometry is not acceptable"


class NotFoundError(GisError):
    status_code = 404
    code = "not_found"
    title = "Resource not found"


class ServiceUnavailableError(GisError):
    status_code = 503
    code = "service_unavailable"
    title = "Service temporarily unavailable"


class PermissionDeniedError(GisError):
    status_code = 403
    code = "forbidden"
    title = "Not permitted"
