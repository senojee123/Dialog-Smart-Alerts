"""HTTP behaviour that does not need a database: probes, error format, request IDs, metrics, CORS."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

REQUEST_ID = "x-request-id"
# Requests act for the tenant in this header (the GIS checks no credentials; see app.core.caller).
AS_TENANT_A = {"X-GIS-Tenant-Id": "tenant-a"}


def unit_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "db_app_password": "unused",
        # Nothing listens on port 1: readiness must fail fast and cleanly.
        "db_host": "127.0.0.1",
        "db_port": 1,
        "db_connect_timeout_s": 1.0,
        "readiness_timeout_s": 3.0,
    }
    values.update(overrides)
    return Settings.model_validate(values)


ClientFactory = Callable[[FastAPI], Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def client_factory() -> AsyncIterator[ClientFactory]:
    """Start an app (running its lifespan) and return an HTTP client bound to it."""
    opened: list[tuple[LifespanManager, httpx.AsyncClient]] = []

    async def make(app: FastAPI) -> httpx.AsyncClient:
        manager = LifespanManager(app)
        await manager.__aenter__()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=manager.app), base_url="http://test")
        opened.append((manager, client))
        return client

    yield make
    for manager, client in reversed(opened):
        await client.aclose()
        await manager.__aexit__(None, None, None)


async def test_liveness_needs_no_database(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "gis-core-service",
        "version": response.json()["version"],
    }
    assert response.headers["cache-control"] == "no-store"
    assert len(response.headers[REQUEST_ID]) == 32


async def test_valid_incoming_request_id_is_echoed_and_invalid_one_replaced(
    client_factory: ClientFactory,
) -> None:
    client = await client_factory(create_app(unit_settings()))
    echoed = await client.get("/health/live", headers={"X-Request-ID": "trace-abc.123"})
    assert echoed.headers[REQUEST_ID] == "trace-abc.123"
    replaced = await client.get("/health/live", headers={"X-Request-ID": "bad id\twith spaces"})
    assert replaced.headers[REQUEST_ID] != "bad id\twith spaces"


async def test_readiness_reports_unreachable_database(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    checks = {check["name"]: check for check in body["checks"]}
    assert checks["database"]["status"] == "fail"
    assert "connection failed" in checks["database"]["error"]
    assert "unused" not in response.text, "credentials must never be echoed"
    for name in (
        "postgis",
        "spatial_reference_systems",
        "crs_consistency",
        "tenant_spatial_indexes",
        "migrations",
    ):
        assert checks[name]["status"] == "skip"


async def test_service_area_is_geojson(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings(service_area_bbox=(79.5, 5.9, 82.0, 9.9))))
    response = await client.get("/geo/v1/service-area")
    assert response.status_code == 200
    feature = response.json()
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Polygon"
    ring = feature["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert {tuple(p) for p in ring} == {(79.5, 5.9), (82.0, 5.9), (82.0, 9.9), (79.5, 9.9)}
    assert feature["properties"]["bbox"] == [79.5, 5.9, 82.0, 9.9]
    assert feature["properties"]["metricCrs"] == "EPSG:5235"


async def test_unknown_route_returns_problem_details(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    response = await client.get("/geo/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["type"] == "urn:gis-core-service:problem:http_404"
    assert problem["status"] == 404
    assert problem["requestId"] == response.headers[REQUEST_ID]


async def test_unhandled_errors_become_opaque_500_problems(client_factory: ClientFactory) -> None:
    app = create_app(unit_settings())

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    client = await client_factory(app)
    response = await client.get("/boom")
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert "hunter2" not in response.text
    assert response.json()["requestId"] == response.headers[REQUEST_ID]


async def test_domain_errors_become_problem_details(client_factory: ClientFactory) -> None:
    from app.core.errors import CoordinateError

    app = create_app(unit_settings())

    @app.get("/bad-coordinate")
    async def bad() -> None:
        raise CoordinateError("position is outside the service area", extensions={"position": [1.0, 2.0]})

    client = await client_factory(app)
    response = await client.get("/bad-coordinate")
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:gis-core-service:problem:invalid_coordinate"
    assert problem["position"] == [1.0, 2.0]


async def test_extensions_cannot_replace_standard_problem_members(client_factory: ClientFactory) -> None:
    from app.core.errors import GisValidationError

    app = create_app(unit_settings())

    @app.get("/clash")
    async def clash() -> None:
        raise GisValidationError("clashing members", extensions={"status": "draft", "type": "x", "hint": 1})

    client = await client_factory(app)
    response = await client.get("/clash")
    assert response.status_code == 422
    problem = response.json()
    assert (problem["status"], problem["type"], problem["hint"]) == (
        422,
        "urn:gis-core-service:problem:validation_error",
        1,
    )


async def test_request_validation_errors_are_problem_details(client_factory: ClientFactory) -> None:
    app = create_app(unit_settings())

    @app.get("/needs-int")
    async def needs_int(radius_m: int) -> dict[str, int]:
        return {"radius_m": radius_m}

    client = await client_factory(app)
    response = await client.get("/needs-int", params={"radius_m": "far"})
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:gis-core-service:problem:request_validation_error"
    assert problem["errors"][0]["loc"] == ["query", "radius_m"]


async def test_metrics_use_route_templates(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    await client.get("/health/live")
    await client.get("/some/random/path/123")
    metrics = (await client.get("/metrics")).text
    assert 'gis_http_requests_total{method="GET",route="/health/live",status="200"} 1.0' in metrics
    assert 'route="<unmatched>",status="404"' in metrics
    assert "/some/random/path/123" not in metrics


async def test_metrics_and_docs_can_be_disabled(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings(metrics_enabled=False, docs_enabled=False)))
    assert (await client.get("/metrics")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404
    assert (await client.get("/docs")).status_code == 404


async def test_openapi_documents_the_foundation_endpoints(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    schema = (await client.get("/openapi.json")).json()
    assert {"/health/live", "/health/ready", "/geo/v1/service-area"} <= set(schema["paths"])


async def test_cors_preflight_only_for_configured_origins(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings(cors_allow_origins=["http://localhost:5173"])))
    headers = {"Access-Control-Request-Method": "GET"}
    allowed = await client.options(
        "/geo/v1/service-area", headers={**headers, "Origin": "http://localhost:5173"}
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert REQUEST_ID in allowed.headers
    denied = await client.options(
        "/geo/v1/service-area", headers={**headers, "Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in denied.headers


def test_missing_runtime_password_fails_at_startup() -> None:
    with pytest.raises(ValueError, match="APP_PASSWORD"):
        create_app(Settings.model_validate({"db_app_password": None}))


# --- POST /geo/v1/enrich without a database ------------------------------------------------------------

ENRICH = "/geo/v1/enrich"


def enrich_body(**fields: object) -> dict[str, object]:
    body: dict[str, object] = {
        "eventId": "evt-unit-1",
        "tenantId": "tenant-a",
        "observedAt": "2026-09-14T08:32:10+05:30",
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": {"type": "Point", "coordinates": [80.749, 8.037]},
    }
    body.update(fields)
    return body


async def test_enrich_needs_no_credentials_and_acts_for_one_tenant(client_factory: ClientFactory) -> None:
    """No token is asked for; an event of a tenant the request does not act for is refused."""
    client = await client_factory(create_app(unit_settings()))
    for headers in ({}, {"X-GIS-Tenant-Id": "tenant-b"}):
        response = await client.post(ENRICH, json=enrich_body(), headers=headers)
        assert response.status_code == 403, response.text
        assert response.json()["type"] == "urn:gis-core-service:problem:forbidden"
        assert response.json()["tenantId"] == "tenant-a"


async def test_the_tenant_header_must_be_a_tenant_id(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    response = await client.post(ENRICH, json=enrich_body(), headers={"X-GIS-Tenant-Id": "Not A Tenant!"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["header", "X-GIS-Tenant-Id"]


@pytest.mark.parametrize(
    ("body", "problem", "member"),
    [
        (enrich_body(eventId=None), "request_validation_error", "errors"),
        (enrich_body(location=None), "request_validation_error", "errors"),
        (
            enrich_body(location={"type": "Point", "coordinates": [8.037, 80.749]}),
            "invalid_coordinate",
            "likelySwapped",
        ),
        (
            enrich_body(location={"type": "Point", "coordinates": [72.83, 18.94]}),
            "invalid_coordinate",
            "serviceAreaBbox",
        ),
        (
            enrich_body(
                location={
                    "type": "Polygon",
                    "coordinates": [[[80.70, 8.0], [80.8, 8.1], [80.8, 8.0], [80.7, 8.1], [80.70, 8.0]]],
                }
            ),
            "invalid_geometry",
            "reason",
        ),
        (enrich_body(observedAt="2099-01-01T00:00:00Z"), "validation_error", "maxClockSkewS"),
    ],
)
async def test_enrich_rejects_invalid_events_before_touching_the_database(
    client_factory: ClientFactory, body: dict[str, object], problem: str, member: str
) -> None:
    client = await client_factory(create_app(unit_settings()))
    response = await client.post(ENRICH, json=body, headers=AS_TENANT_A)
    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    payload = response.json()
    assert payload["type"] == f"urn:gis-core-service:problem:{problem}"
    assert member in payload


async def test_enrich_rejects_non_finite_coordinates(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    raw = json.dumps(enrich_body()).replace("[80.749, 8.037]", "[80.749, NaN]")
    response = await client.post(
        ENRICH,
        content=raw,
        headers={"Content-Type": "application/json", **AS_TENANT_A},
    )
    assert response.status_code == 422
    assert response.json()["type"] == "urn:gis-core-service:problem:invalid_coordinate"


async def test_enrich_validates_the_release_parameter(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    response = await client.post(
        ENRICH,
        params={"refDataRelease": "latest; DROP TABLE ref.road"},
        json=enrich_body(),
        headers=AS_TENANT_A,
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["query", "refDataRelease"]


async def test_oversized_bodies_are_rejected(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings(max_request_body_bytes=2048)))
    body = enrich_body(metadata={"padding": "x" * 4000})
    declared = await client.post(ENRICH, json=body, headers=AS_TENANT_A)
    assert declared.status_code == 413
    assert declared.json()["type"] == "urn:gis-core-service:problem:payload_too_large"
    assert declared.json()["requestId"] == declared.headers[REQUEST_ID]

    async def chunks() -> AsyncIterator[bytes]:
        encoded = json.dumps(body).encode()
        for start in range(0, len(encoded), 1000):
            yield encoded[start : start + 1000]

    streamed = await client.post(
        ENRICH,
        content=chunks(),
        headers={"Content-Type": "application/json", **AS_TENANT_A},
    )
    assert streamed.status_code == 413
    assert streamed.json()["type"] == "urn:gis-core-service:problem:payload_too_large"


async def test_openapi_documents_the_enrich_endpoint(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    schema = (await client.get("/openapi.json")).json()
    operation = schema["paths"][ENRICH]["post"]
    assert operation["operationId"] == "enrichEvent"
    assert "security" not in operation
    assert "securitySchemes" not in schema.get("components", {})
    assert {"200", "403", "404", "413", "422", "503"} <= set(operation["responses"])
    assert "401" not in operation["responses"]
    assert [p["name"] for p in operation["parameters"] if p["in"] == "header"] == ["X-GIS-Tenant-Id"]
    problem = operation["responses"]["422"]["content"]["application/problem+json"]["schema"]
    assert problem == {"$ref": "#/components/schemas/ProblemDetail"}
    assert "ProblemDetail" in schema["components"]["schemas"]
    assert set(operation["requestBody"]["content"]["application/json"]["examples"]) == {
        "point",
        "device",
        "line",
    }
    context = schema["components"]["schemas"]["GeoContext"]
    assert {"schema", "insideZones", "refDataRelease", "computedAt"} <= set(context["required"])
    # Consumer-neutral API (ARCHITECTURE.md 2.2): no member names about recipients or alerts.
    members = {
        name.lower()
        for model in schema["components"]["schemas"].values()
        for name in model.get("properties", {})
    }
    assert not {m for m in members if any(word in m for word in ("recipient", "notif", "alert"))}


async def test_the_platform_image_serves_the_map_and_basemaps_with_range_requests(
    client_factory: ClientFactory, tmp_path: Path
) -> None:
    web, basemap = tmp_path / "web", tmp_path / "basemap"
    web.mkdir()
    basemap.mkdir()
    (web / "index.html").write_text("<!doctype html><title>map</title>", encoding="utf-8")
    (basemap / "tiles.pmtiles").write_bytes(bytes(range(256)))
    client = await client_factory(create_app(unit_settings(web_dir=web, basemap_dir=basemap)))

    page = await client.get("/app/")
    assert page.status_code == 200
    assert "<title>map</title>" in page.text
    part = await client.get("/basemap/tiles.pmtiles", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == bytes(range(10, 20))


async def test_static_files_are_not_served_unless_configured(client_factory: ClientFactory) -> None:
    client = await client_factory(create_app(unit_settings()))
    assert (await client.get("/app/")).status_code == 404
    assert (await client.get("/basemap/style.json")).status_code == 404
