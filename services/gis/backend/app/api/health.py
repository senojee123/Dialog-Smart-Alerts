"""Liveness and readiness probes.

* ``GET /health/live``  - the process is running. No dependencies are touched; use for restarts.
* ``GET /health/ready`` - the service can answer spatial requests correctly. Returns 503 otherwise;
  use for load-balancer membership and deployment gates.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app import SERVICE_NAME, __version__
from app.api.deps import ReadinessServiceDep
from app.schemas.health import CheckResultModel, LivenessResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])

_NO_STORE = "no-store"


@router.get("/live", response_model=LivenessResponse, summary="Liveness probe")
async def live(response: Response) -> LivenessResponse:
    response.headers["Cache-Control"] = _NO_STORE
    return LivenessResponse(service=SERVICE_NAME, version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse, "description": "Not ready"}},
)
async def ready(response: Response, readiness: ReadinessServiceDep) -> ReadinessResponse:
    report = await readiness.check()
    response.headers["Cache-Control"] = _NO_STORE
    if not report.ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if report.ready else "not_ready",
        service=SERVICE_NAME,
        version=__version__,
        checks=[
            CheckResultModel(
                name=check.name,
                status=check.status.value,
                duration_ms=check.duration_ms,
                detail=check.detail,
                error=check.error,
            )
            for check in report.checks
        ],
    )
