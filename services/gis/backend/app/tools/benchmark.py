"""Measure geo-enrichment and spatial API latency, and capture the query plans behind them.

Usage (from ``backend/``, against a development database with a reference data release, e.g. the
development sample, and the ``GIS_DB_*`` settings of the API)::

    python -m app.tools.benchmark --output benchmark.json

The application is built in-process exactly as it runs (``create_app``), and requests go through the
whole HTTP stack - validation, services, PostGIS, row-level security, the audit log - but not a network.

What is measured, after a warm-up:

* ``POST /geo/v1/enrich`` for events at positions spread over the pilot area and the country;
* the queries the map and other services make: layer features in a viewport, within-distance, nearest,
  containment, reverse geocoding, and events in a window.

For each operation the statements the service executed are captured and replayed with
``EXPLAIN (ANALYZE, BUFFERS)`` in the same tenant context, so the plans are those of the real queries
with real parameters. Enrichment stores its events (event type ``benchmark.synthetic``) in the tenant
given; use a development tenant. Refuses to run with ``GIS_ENV=production``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import json
import math
import statistics
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from app.core.caller import TENANT_HEADER
from app.core.config import DbRole, Environment, Settings, get_settings
from app.core.logging import configure_logging
from app.db.engine import create_engine
from app.main import create_app
from app.tools.seed_dev_data import SAMPLE_RELEASE_PURPOSES

# Positions: a low-discrepancy sequence over the pilot area (dense reference data) and the country.
PILOT: Final = (80.45, 7.75, 81.10, 8.30)
NATIONAL: Final = (79.90, 6.00, 81.80, 9.60)
VIEWPORT_DEG: Final = 0.02  # about 2.2 km: a town at zoom 13-14
EVENT_TYPE: Final = "benchmark.synthetic"
PLANNED: Final = ("SELECT", "WITH")


def positions(
    count: int, area: tuple[float, float, float, float], offset: int = 0
) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = area
    return [
        (
            round(x0 + math.modf((i + offset) * 0.6180339887)[0] * (x1 - x0), 6),
            round(y0 + math.modf((i + offset) * 0.7548776662)[0] * (y1 - y0), 6),
        )
        for i in range(1, count + 1)
    ]


@dataclass(slots=True)
class Operation:
    name: str
    samples_ms: list[float] = field(default_factory=list)
    errors: dict[int, int] = field(default_factory=dict)
    statements: list[tuple[str, Any]] = field(default_factory=list)
    plans: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.samples_ms)

        def percentile(p: float) -> float:
            if not ordered:
                return math.nan
            index = min(len(ordered) - 1, max(0, math.ceil(p / 100 * len(ordered)) - 1))
            return round(ordered[index], 2)

        return {
            "operation": self.name,
            "requests": len(ordered),
            "errors": self.errors,
            "meanMs": round(statistics.fmean(ordered), 2) if ordered else None,
            "p50Ms": percentile(50),
            "p95Ms": percentile(95),
            "p99Ms": percentile(99),
            "maxMs": round(ordered[-1], 2) if ordered else None,
            "samplesMs": [round(sample, 2) for sample in self.samples_ms],
            "plans": self.plans,
        }


class Recorder:
    """Keeps the statements each operation executed (the first request after warm-up only)."""

    def __init__(self) -> None:
        self.operations: dict[str, Operation] = {}
        # Requests are made one at a time, so the statement being executed belongs to this one.
        self.capturing: str | None = None

    def __call__(  # SQLAlchemy before_cursor_execute signature
        self, conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if self.capturing is not None:
            self.operations[self.capturing].statements.append((statement, parameters))


async def timed(
    recorder: Recorder, name: str, call: Callable[[], Awaitable[httpx.Response]], *, capture: bool
) -> None:
    operation = recorder.operations.setdefault(name, Operation(name))
    recorder.capturing = name if capture else None
    started = time.perf_counter()
    try:
        response = await call()
    finally:
        elapsed = (time.perf_counter() - started) * 1000
        recorder.capturing = None
    if response.status_code >= 400:
        operation.errors[response.status_code] = operation.errors.get(response.status_code, 0) + 1
        if capture:
            operation.statements.clear()
        return
    operation.samples_ms.append(elapsed)


def _plan_nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


def summarise_plan(statement: str, explained: dict[str, Any]) -> dict[str, Any]:
    root = explained["Plan"]
    nodes = _plan_nodes(root)
    scans = [
        {
            "node": node["Node Type"],
            "relation": node.get("Relation Name"),
            "index": node.get("Index Name"),
            "rows": node.get("Actual Rows"),
            "loops": node.get("Actual Loops"),
        }
        for node in nodes
        if "Scan" in node["Node Type"]
        and (node.get("Relation Name") is not None or node.get("Index Name") is not None)
    ]
    return {
        "statement": " ".join(statement.split())[:240],
        "planningMs": round(explained.get("Planning Time", 0.0), 3),
        "executionMs": round(explained.get("Execution Time", 0.0), 3),
        "sharedHitBlocks": root.get("Shared Hit Blocks"),
        "sharedReadBlocks": root.get("Shared Read Blocks"),
        "sequentialScans": sorted({f"{scan['relation']}" for scan in scans if scan["node"] == "Seq Scan"}),
        "indexScans": sorted(
            {f"{scan['relation'] or 'bitmap'}:{scan['index']}" for scan in scans if scan["index"]}
        ),
        "jit": "JIT" in explained,
    }


async def explain(settings: Settings, operation: Operation) -> None:
    """Replay the operation's statements in one rolled-back transaction, explaining the queries."""
    engine = create_engine(settings, DbRole.APP)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                for statement, parameters in operation.statements:
                    head = statement.lstrip().split(None, 1)[0].upper()
                    if "set_config" in statement:
                        await connection.exec_driver_sql(statement, parameters)
                        continue
                    if head not in PLANNED or "INSERT" in statement.upper() or "UPDATE " in statement.upper():
                        continue
                    result = await connection.exec_driver_sql(
                        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters
                    )
                    document = result.scalar_one()
                    explained = (json.loads(document) if isinstance(document, str) else document)[0]
                    operation.plans.append(summarise_plan(statement, explained))
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def table_sizes(settings: Settings) -> dict[str, int]:
    engine = create_engine(settings, DbRole.APP)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    """
                    SELECT n.nspname || '.' || c.relname AS name, c.reltuples::bigint AS rows
                    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname IN ('ref', 'ops', 'geo', 'meta', 'audit') AND c.relkind IN ('r', 'p')
                      AND c.relname !~ '_p[0-9]{6}$'
                    ORDER BY 1
                    """
                )
            )
            return {row.name: int(row.rows) for row in rows}
    finally:
        await engine.dispose()


async def refuse_operational_release(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    response = await client.get("/geo/v1/releases", headers=headers)
    if response.status_code != 200:
        raise SystemExit(f"the service did not list its releases ({response.status_code}): {response.text}")
    current = [release for release in response.json()["releases"] if release.get("isCurrent")]
    if not current:
        raise SystemExit("the service has no current reference data release")
    release = current[0]
    if release.get("purpose") not in SAMPLE_RELEASE_PURPOSES:
        raise SystemExit(
            f"the current reference data release {release.get('code')} is a {release.get('purpose')} "
            "release; the benchmark writes events and only runs next to development or test releases"
        )


async def run(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    if settings.env == Environment.PRODUCTION:
        raise SystemExit("the benchmark writes events; it does not run with GIS_ENV=production")
    # Every request acts for the tenant measured (the GIS checks no credentials; see app.core.caller).
    as_person = as_pipeline = {TENANT_HEADER: args.tenant}
    recorder = Recorder()
    event.listen(Engine, "before_cursor_execute", recorder)
    run_id = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    window = {"from": (now - timedelta(hours=24)).isoformat(), "to": (now + timedelta(minutes=5)).isoformat()}
    points = positions(args.events, PILOT) + positions(args.events // 4, NATIONAL, offset=7)
    query_points = positions(args.queries, PILOT, offset=101)
    try:
        async with contextlib.AsyncExitStack() as stack:
            if args.api_url is None:
                app = create_app(settings)
                await stack.enter_async_context(app.router.lifespan_context(app))
                client = await stack.enter_async_context(
                    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://benchmark")
                )
            else:
                # A running API over HTTP: the network and the server are measured too, and the statements
                # run in another process, so no query plans are captured.
                client = await stack.enter_async_context(httpx.AsyncClient(base_url=args.api_url, timeout=30))

            # The benchmark writes events into the tenant it measures: only next to a development or test
            # release, asked of the service measured (GIS_ENV describes this process, not a remote API).
            await refuse_operational_release(client, as_person)

            async def enrich(index: int, lon: float, lat: float) -> httpx.Response:
                return await client.post(
                    "/geo/v1/enrich",
                    headers=as_pipeline,
                    json={
                        "eventId": f"bench-{run_id}-{index}",
                        "tenantId": args.tenant,
                        "observedAt": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                        "eventType": EVENT_TYPE,
                        "sourceType": "sensor",
                        "locationSource": "sensor",
                        "location": {"type": "Point", "coordinates": [lon, lat]},
                    },
                )

            def viewport(lon: float, lat: float) -> str:
                half = VIEWPORT_DEG / 2
                return f"{lon - half},{lat - half},{lon + half},{lat + half}"

            queries: dict[str, Callable[[float, float], Awaitable[httpx.Response]]] = {
                "features ref.road (viewport)": lambda lon, lat: client.get(
                    "/geo/v1/layers/ref.road/features", headers=as_person, params={"bbox": viewport(lon, lat)}
                ),
                "features ref.admin_area (viewport)": lambda lon, lat: client.get(
                    "/geo/v1/layers/ref.admin_area/features",
                    headers=as_person,
                    params={"bbox": viewport(lon, lat), "level": 4},
                ),
                "features ops.geofence (viewport)": lambda lon, lat: client.get(
                    "/geo/v1/layers/ops.geofence/features",
                    headers=as_person,
                    params={"bbox": viewport(lon, lat), "tenantId": args.tenant},
                ),
                "within-distance ref.facility 5 km": lambda lon, lat: client.post(
                    "/geo/v1/query/within-distance",
                    headers=as_person,
                    json={
                        "target": "ref.facility",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "distanceM": 5000,
                    },
                ),
                "nearest ref.settlement": lambda lon, lat: client.post(
                    "/geo/v1/query/nearest",
                    headers=as_person,
                    json={
                        "target": "ref.settlement",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "limit": 5,
                    },
                ),
                "contains ref.admin_area": lambda lon, lat: client.post(
                    "/geo/v1/query/contains",
                    headers=as_person,
                    json={
                        "target": "ref.admin_area",
                        "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    },
                ),
                "reverse": lambda lon, lat: client.get(
                    "/geo/v1/reverse", headers=as_person, params={"lon": lon, "lat": lat}
                ),
                "events (10 km, 24 h)": lambda lon, lat: client.get(
                    "/geo/v1/events",
                    headers=as_person,
                    params={
                        **window,
                        "tenantId": args.tenant,
                        "bbox": f"{lon - 0.05},{lat - 0.05},{lon + 0.05},{lat + 0.05}",
                    },
                ),
            }
            # Warm-up: connections, caches, prepared plans.
            for index, (lon, lat) in enumerate(points[: args.warmup]):
                await enrich(-1 - index, lon, lat)
            for query in queries.values():
                for lon, lat in query_points[: args.warmup]:
                    await query(lon, lat)
            for index, (lon, lat) in enumerate(points):
                await timed(
                    recorder,
                    "POST /geo/v1/enrich",
                    functools.partial(enrich, index, lon, lat),
                    capture=index == 0,
                )
            for name, query in queries.items():
                for index, (lon, lat) in enumerate(query_points):
                    await timed(
                        recorder,
                        name,
                        functools.partial(query, lon, lat),
                        capture=index == 0,
                    )
    finally:
        event.remove(Engine, "before_cursor_execute", recorder)
    if args.explain:
        for operation in recorder.operations.values():
            await explain(settings, operation)
    return {
        "measuredAt": datetime.now(UTC).isoformat(),
        "target": args.api_url or "in-process application (no network)",
        "tenant": args.tenant,
        "events": len(points),
        "queriesPerOperation": len(query_points),
        # Row counts come from the local database, which is the one measured only in process.
        "tables": await table_sizes(settings) if args.api_url is None else None,
        "operations": [operation.summary() for operation in recorder.operations.values()],
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        "| Operation | Requests | p50 ms | p95 ms | p99 ms | max ms | Errors |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in report["operations"]:
        errors = ", ".join(f"{code}: {count}" for code, count in item["errors"].items()) or "0"
        lines.append(
            f"| {item['operation']} | {item['requests']} | {item['p50Ms']} | {item['p95Ms']} | "
            f"{item['p99Ms']} | {item['maxMs']} | {errors} |"
        )
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tenant", default="wildlife-dept", help="a registered development tenant")
    parser.add_argument("--events", type=int, default=200, help="events to enrich in the pilot area")
    parser.add_argument("--queries", type=int, default=100, help="requests per query operation")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--no-explain", dest="explain", action="store_false", help="skip the query plans")
    parser.add_argument("--output", type=Path, help="write the full report (JSON) here")
    parser.add_argument(
        "--api-url", help="measure a running API over HTTP instead of the in-process application"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # The application logs every request at INFO; the measurements are the output here.
    settings = get_settings().model_copy(update={"log_level": "WARNING"})
    configure_logging("WARNING", settings.log_format, stream=sys.stderr)
    report = asyncio.run(run(args, settings))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
    print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
