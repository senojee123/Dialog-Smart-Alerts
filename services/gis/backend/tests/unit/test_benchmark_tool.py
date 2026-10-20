"""The benchmark tool's own arithmetic (positions, percentiles, plan summaries) and its guard."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.tools.benchmark import (
    NATIONAL,
    PILOT,
    Operation,
    positions,
    refuse_operational_release,
    render,
    summarise_plan,
)


def releases(*items: dict[str, Any]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/geo/v1/releases"
        return httpx.Response(200, json={"releases": list(items)})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://service")


async def test_it_runs_next_to_a_development_release() -> None:
    async with releases(
        {"code": "ref-v1", "purpose": "operational", "isCurrent": False},
        {"code": "ref-2026.09-dev", "purpose": "development", "isCurrent": True},
    ) as client:
        await refuse_operational_release(client, {})


@pytest.mark.parametrize(
    "items",
    [
        ({"code": "ref-v1", "purpose": "operational", "isCurrent": True},),
        ({"code": "ref-2026.09-dev", "purpose": "development", "isCurrent": False},),
        (),
    ],
    ids=["operational release", "no current release", "no release"],
)
async def test_it_refuses_a_service_without_a_development_release(items: tuple[dict[str, Any], ...]) -> None:
    async with releases(*items) as client:
        with pytest.raises(SystemExit):
            await refuse_operational_release(client, {})


def test_positions_are_deterministic_and_inside_the_area() -> None:
    first = positions(50, PILOT)
    assert first == positions(50, PILOT)
    assert len(set(first)) == 50
    x0, y0, x1, y1 = PILOT
    assert all(x0 <= lon <= x1 and y0 <= lat <= y1 for lon, lat in first)
    assert positions(5, NATIONAL, offset=7) != positions(5, NATIONAL)


def test_percentiles_use_the_nearest_rank() -> None:
    operation = Operation("x", samples_ms=[float(value) for value in range(1, 101)])
    summary = operation.summary()
    assert (summary["p50Ms"], summary["p95Ms"], summary["p99Ms"], summary["maxMs"]) == (50, 95, 99, 100)
    assert summary["requests"] == 100
    assert "| x | 100 | 50.0 | 95.0 | 99.0 | 100.0 | 0 |" in render({"operations": [summary]})


def test_a_plan_summary_names_sequential_and_index_scans() -> None:
    explained = {
        "Planning Time": 1.5,
        "Execution Time": 2.25,
        "Plan": {
            "Node Type": "Nested Loop",
            "Shared Hit Blocks": 40,
            "Plans": [
                {"Node Type": "Seq Scan", "Relation Name": "device", "Actual Rows": 3, "Actual Loops": 1},
                {
                    "Node Type": "Index Scan",
                    "Relation Name": "road",
                    "Index Name": "ix_road_release_id_geom_metric_gist",
                    "Actual Rows": 1,
                    "Actual Loops": 1,
                },
                {"Node Type": "Bitmap Index Scan", "Index Name": "event_location_p202609_geom_idx"},
            ],
        },
    }
    summary = summarise_plan("SELECT  *\n FROM x", explained)
    assert summary["statement"] == "SELECT * FROM x"
    assert (summary["planningMs"], summary["executionMs"], summary["sharedHitBlocks"]) == (1.5, 2.25, 40)
    assert summary["sequentialScans"] == ["device"]
    assert summary["indexScans"] == [
        "bitmap:event_location_p202609_geom_idx",
        "road:ix_road_release_id_geom_metric_gist",
    ]
    assert summary["jit"] is False
