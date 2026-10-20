"""An HTTP client against the real application.

The application is built exactly as it is in production (``create_app``), with the test database, so
requests go through the tenant the request acts for, the services, PostGIS and row-level security. A request
acts for the tenant in its ``X-GIS-Tenant-Id`` header (see ``app.core.caller``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Final

import httpx
from asgi_lifespan import LifespanManager

from app.core.caller import TENANT_HEADER
from app.core.tenancy import TenantId
from app.main import create_app
from tests.integration.conftest import SpatialWorld

PROBLEM: Final = "urn:gis-core-service:problem:"
# The tenant requests act for when they name none: registered in no test world.
UNREGISTERED_DEFAULT: Final = "unregistered-default"


@dataclass(frozen=True, slots=True)
class Api:
    client: httpx.AsyncClient
    world: SpatialWorld

    @staticmethod
    def headers(tenant: TenantId | None = None) -> dict[str, str]:
        """Headers of a request acting for ``tenant`` (none: the default tenant of the settings)."""
        return {} if tenant is None else {TENANT_HEADER: tenant.value}

    async def request(
        self,
        method: str,
        path: str,
        *,
        tenant: TenantId | None = None,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.client.request(
            method,
            path,
            params=params,
            json=json,
            headers=headers if headers is not None else self.headers(tenant),
        )

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self.request("DELETE", path, **kwargs)


@asynccontextmanager
async def api_client_for(world: SpatialWorld, **overrides: Any) -> AsyncIterator[Api]:
    settings = world.settings.model_copy(update={"tenant_id": UNREGISTERED_DEFAULT, **overrides})
    app = create_app(settings)
    async with (
        LifespanManager(app) as manager,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=manager.app), base_url="http://test") as client,
    ):
        yield Api(client, world)


def assert_problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    """Every error is an RFC 9457 problem naming its code, and carries the request id."""
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    problem: dict[str, Any] = response.json()
    assert problem["type"] == f"{PROBLEM}{code}", problem
    assert problem["status"] == status
    assert problem["requestId"] == response.headers["x-request-id"]
    return problem


def ok(response: httpx.Response, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    return body


def feature_names(collection: dict[str, Any]) -> list[str]:
    return [feature["properties"]["name"] for feature in collection["features"]]


def feature_ids(collection: dict[str, Any]) -> list[str]:
    return [feature["id"] for feature in collection["features"]]
