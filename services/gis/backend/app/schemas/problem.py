"""RFC 9457 problem details."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_TYPE_PREFIX = "urn:gis-core-service:problem:"


class ProblemDetail(BaseModel):
    """Error body.

    Extension members (``requestId``, ``errors`` and problem-specific fields) may be present.
    """

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    requestId: str | None = None  # noqa: N815 - wire format is camelCase

    def to_body(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
