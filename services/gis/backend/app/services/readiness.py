"""Readiness checks.

The service is ready only when it can serve correct spatial answers: the database is reachable,
PostGIS meets the minimum version, the coordinate systems the service depends on exist, and the
schema is at the migration head this build expects.

Check outcomes:

* ``pass`` - requirement met
* ``warn`` - service can run, but an operator should look (does not affect readiness)
* ``fail`` - requirement not met; the service reports not ready
* ``skip`` - not evaluated because an earlier check failed (counts as not ready)
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.repositories.database_info import DatabaseInfoRepository
from app.spatial import crs

logger = logging.getLogger(__name__)

# Natural origin of EPSG:5235 expressed as WGS84 degrees; a stable probe point in central Sri Lanka.
CRS_PROBE_LON = 80.77171308333334
CRS_PROBE_LAT = 7.000471527777778


class CheckStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - not a secret
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    duration_ms: float
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    checks: tuple[CheckResult, ...]


class _CheckFailedError(Exception):
    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class _CheckWarningError(Exception):
    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


def _parse_version(value: str) -> tuple[int, int]:
    parts = value.split(".")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError) as exc:
        raise _CheckFailedError(f"unrecognised version string {value!r}") from exc


def _describe_error(exc: BaseException) -> str:
    # Class name only: driver messages can contain user names or host details.
    return f"{type(exc).__name__}"


class ReadinessService:
    def __init__(
        self, engine: AsyncEngine, settings: Settings, migration_heads: frozenset[str] | None
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._migration_heads = migration_heads

    async def check(self) -> ReadinessReport:
        try:
            async with asyncio.timeout(self._settings.readiness_timeout_s):
                checks = await self._run_checks()
        except TimeoutError:
            checks = (
                CheckResult(
                    name="database",
                    status=CheckStatus.FAIL,
                    duration_ms=self._settings.readiness_timeout_s * 1000,
                    error=f"readiness checks exceeded {self._settings.readiness_timeout_s}s",
                ),
            )
        ready = all(c.status in (CheckStatus.PASS, CheckStatus.WARN) for c in checks)
        return ReadinessReport(ready=ready, checks=checks)

    async def _run_checks(self) -> tuple[CheckResult, ...]:
        started = time.perf_counter()
        try:
            connection = await self._engine.connect()
        except Exception as exc:
            logger.warning("readiness: database connection failed", exc_info=True)
            failed = CheckResult(
                name="database",
                status=CheckStatus.FAIL,
                duration_ms=_elapsed_ms(started),
                error=f"connection failed ({_describe_error(exc)})",
            )
            skipped = tuple(
                CheckResult(name=name, status=CheckStatus.SKIP, duration_ms=0.0, error="database unavailable")
                for name in (
                    "postgis",
                    "spatial_reference_systems",
                    "crs_consistency",
                    "tenant_spatial_indexes",
                    "migrations",
                )
            )
            return (failed, *skipped)

        try:
            # Each probe runs as its own statement so one failing query cannot abort the others.
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            repo = DatabaseInfoRepository(connection)
            results = [
                await _timed("database", lambda: self._check_database(repo), started=started),
            ]
            postgis = await _timed("postgis", lambda: self._check_postgis(repo))
            results.append(postgis)
            if postgis.status is CheckStatus.FAIL:
                results.extend(
                    CheckResult(
                        name=name, status=CheckStatus.SKIP, duration_ms=0.0, error="PostGIS unavailable"
                    )
                    for name in ("spatial_reference_systems", "crs_consistency", "tenant_spatial_indexes")
                )
            else:
                results.append(await _timed("spatial_reference_systems", lambda: self._check_srids(repo)))
                results.append(await _timed("crs_consistency", lambda: self._check_crs_consistency(repo)))
                results.append(
                    await _timed("tenant_spatial_indexes", lambda: self._check_tenant_spatial_indexes(repo))
                )
            results.append(await _timed("migrations", lambda: self._check_migrations(repo)))
            return tuple(results)
        finally:
            await connection.close()

    @staticmethod
    async def _check_database(repo: DatabaseInfoRepository) -> dict[str, Any]:
        info = await repo.server_info()
        return {"serverVersion": info.server_version, "database": info.database}

    async def _check_postgis(self, repo: DatabaseInfoRepository) -> dict[str, Any]:
        info = await repo.postgis_info()
        if info is None:
            raise _CheckFailedError("PostGIS extension is not installed")
        detail = {
            "extensionVersion": info.extension_version,
            "libVersion": info.lib_version,
            "geosVersion": info.geos_version,
            "projVersion": info.proj_version,
            "minimumVersion": self._settings.postgis_min_version,
        }
        if _parse_version(info.lib_version) < self._settings.postgis_min_version_tuple:
            raise _CheckFailedError(
                f"PostGIS {info.lib_version} is older than the required {self._settings.postgis_min_version}",
                detail,
            )
        if info.extension_version != info.lib_version:
            raise _CheckWarningError(
                "PostGIS extension version differs from the library version; "
                "run ALTER EXTENSION postgis UPDATE",
                detail,
            )
        return detail

    @staticmethod
    async def _check_srids(repo: DatabaseInfoRepository) -> dict[str, Any]:
        present = await repo.present_srids(crs.REQUIRED_SRIDS)
        missing = sorted(crs.REQUIRED_SRIDS - present)
        detail = {"required": sorted(crs.REQUIRED_SRIDS), "missing": missing}
        if missing:
            raise _CheckFailedError(
                "required spatial reference systems are missing from spatial_ref_sys", detail
            )
        return detail

    async def _check_crs_consistency(self, repo: DatabaseInfoRepository) -> dict[str, Any]:
        """The database and the application must transform WGS84 -> SLD99 the same way."""
        db_x, db_y = await repo.transform_point(CRS_PROBE_LON, CRS_PROBE_LAT, crs.WGS84, crs.SLD99_GRID)
        app_x, app_y = crs.wgs84_to_metric_xy(CRS_PROBE_LON, CRS_PROBE_LAT)
        offset = math.hypot(db_x - app_x, db_y - app_y)
        detail = {
            "probe": [CRS_PROBE_LON, CRS_PROBE_LAT],
            "offsetM": round(offset, 4),
            "toleranceM": self._settings.crs_consistency_tolerance_m,
            "applicationProjVersion": crs.proj_version(),
        }
        if offset > self._settings.crs_consistency_tolerance_m:
            raise _CheckWarningError(
                "database and application disagree on the WGS84 -> EPSG:5235 transformation", detail
            )
        return detail

    @staticmethod
    async def _check_tenant_spatial_indexes(repo: DatabaseInfoRepository) -> dict[str, Any]:
        """Row-level security uses a spatial index only if the && operator is LEAKPROOF."""
        leakproof = await repo.overlap_operator_is_leakproof()
        detail = {"overlapOperatorLeakproof": leakproof}
        if not leakproof:
            raise _CheckWarningError(
                "spatial indexes cannot be used on tenant tables under row-level security; "
                "run db/admin/postgis-leakproof.sql as a superuser",
                detail,
            )
        return detail

    async def _check_migrations(self, repo: DatabaseInfoRepository) -> dict[str, Any]:
        if self._migration_heads is None:
            raise _CheckFailedError("migration scripts could not be loaded by this build")
        applied = await repo.migration_revisions()
        detail = {"expected": sorted(self._migration_heads), "applied": sorted(applied or [])}
        if applied is None:
            raise _CheckFailedError("database has not been migrated", detail)
        if applied != self._migration_heads:
            raise _CheckFailedError("database schema revision does not match this build", detail)
        return detail


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


async def _timed(
    name: str,
    check: Callable[[], Awaitable[dict[str, Any]]],
    *,
    started: float | None = None,
) -> CheckResult:
    begin = time.perf_counter() if started is None else started
    try:
        detail = await check()
    except _CheckFailedError as exc:
        return CheckResult(name, CheckStatus.FAIL, _elapsed_ms(begin), exc.detail, str(exc))
    except _CheckWarningError as exc:
        return CheckResult(name, CheckStatus.WARN, _elapsed_ms(begin), exc.detail, str(exc))
    except Exception as exc:
        logger.warning("readiness check %s raised", name, exc_info=True)
        return CheckResult(
            name, CheckStatus.FAIL, _elapsed_ms(begin), {}, f"check error ({_describe_error(exc)})"
        )
    return CheckResult(name, CheckStatus.PASS, _elapsed_ms(begin), detail)
