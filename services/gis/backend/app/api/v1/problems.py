"""OpenAPI documentation for the error responses (RFC 9457 problem details).

Every endpoint documents the problems a client has to handle, each with the ``type`` URN that identifies
it. The bodies all have the same shape (``app.schemas.problem.ProblemDetail``), so only the example
differs per case.
"""

from __future__ import annotations

from typing import Any, Final

from app.core.access import Permission
from app.schemas.problem import PROBLEM_CONTENT_TYPE, PROBLEM_TYPE_PREFIX

EXAMPLE_REQUEST_ID: Final = "5f0c6f0f2f5c4b1f9a55c6f1d2a7e3b4"


def problem(
    status: int, code: str, title: str, description: str, instance: str = "/geo/v1"
) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            PROBLEM_CONTENT_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProblemDetail"},
                "example": {
                    "type": f"{PROBLEM_TYPE_PREFIX}{code}",
                    "title": title,
                    "status": status,
                    "detail": description,
                    "instance": instance,
                    "requestId": EXAMPLE_REQUEST_ID,
                },
            }
        },
    }


def forbidden(instance: str, detail: str) -> dict[str, Any]:
    return problem(403, "forbidden", "Not permitted", detail, instance)


OTHER_TENANT: Final = (
    "`tenantId` names a tenant other than the one the request acts for (the `X-GIS-Tenant-Id` header, else "
    "the platform's organisation)."
)


def other_tenant(instance: str) -> dict[str, Any]:
    return forbidden(instance, OTHER_TENANT)


def unavailable(instance: str, detail: str) -> dict[str, Any]:
    return problem(503, "service_unavailable", "Service temporarily unavailable", detail, instance)


def requires(*permissions: Permission, **conditional: Permission) -> dict[str, Any]:
    """OpenAPI extension naming the permissions an operation checks (``x-gis-permissions``).

    ``conditional`` names permissions needed only with a parameter, e.g. ``purge=Permission.DATA_PURGE``.
    A test holds every operation to declaring them.
    """
    extension: dict[str, Any] = {"x-gis-permissions": [permission.value for permission in permissions]}
    if conditional:
        extension["x-gis-conditional-permissions"] = {
            parameter: permission.value for parameter, permission in conditional.items()
        }
    return extension
