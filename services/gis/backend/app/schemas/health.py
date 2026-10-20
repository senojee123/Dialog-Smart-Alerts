"""Health endpoint response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.base import ApiModel


class LivenessResponse(ApiModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str


class CheckResultModel(ApiModel):
    name: str
    status: Literal["pass", "warn", "fail", "skip"]
    duration_ms: float = Field(description="Time spent on this check, in milliseconds.")
    detail: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ReadinessResponse(ApiModel):
    status: Literal["ready", "not_ready"]
    service: str
    version: str
    checks: list[CheckResultModel]
