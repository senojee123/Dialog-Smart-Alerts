"""Tenant isolation: tenant A cannot retrieve tenant B's operational GIS data.

The proof is made at every layer a request passes through, against the real database and the real
application (``create_app``), each request acting for one tenant (``X-GIS-Tenant-Id``) as in production:

* **database** - every table that holds tenant data carries ``tenant_id`` and is protected by row-level
  security; with tenant A's context the runtime login sees none of B's private rows in any of them, cannot
  change them and cannot write rows for B; without a tenant it sees no tenant rows at all; the context
  ends with the transaction;
* **API** - every endpoint that reads or changes tenant data answers A without B's private data: map
  features and spatial questions on operational layers, geofences, sites, device placements, events, exports
  and the audit log. Naming B in ``tenantId`` is refused; other tenant headers or a tenant in a request
  body are not a way around it; a cursor from B's answers does not work for A.

The seeded world gives B private objects of every kind (geofences, a site, devices, a field of view, events
with geo-context and geofence hits, audit entries) right next to A's, plus objects B shares with A and with
authorities, so each check can fail. ``test_every_tenant_data_endpoint_is_covered`` holds new endpoints to
being added here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import transaction
from app.schemas.events import EventLocationIn
from app.services.enrichment import GeoContextLimits, GeoContextService
from tests.integration.api_client import Api, api_client_for, assert_problem, ok
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import AUTHORITY, CENTRE, SYNTHETIC_RELEASE, TENANT_A, TENANT_B

EVENTS: Final = "/geo/v1/events"
WINDOW: Final = {"from": "2026-09-12T00:00:00Z", "to": "2026-09-13T00:00:00Z"}
AROUND_CENTRE: Final = "80.70,7.98,80.80,8.08"
# Inside several synthetic risk zones, so an event there has zone hits (as test_event_query_api uses it).
MULTI_ZONE_POINT: Final = (80.758, 8.015)
TENANT_SCHEMAS: Final = ("ops", "geo", "audit")
OPERATIONAL_LAYERS: Final = ("ops.site", "ops.device", "ops.device_field_of_view", "ops.geofence")


def _point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


@dataclass(frozen=True, slots=True)
class Isolation:
    """B's private objects (which A must never see) and what A may legitimately see of B."""

    b_site: str
    b_device: str
    b_private_fence: str
    b_authority_fence: str
    b_shared_fence: str
    b_shared_device: str
    b_event: str
    b_zone_event: str
    a_event: str
    a_site: str

    @property
    def private_to_b(self) -> set[str]:
        return {
            self.b_site,
            self.b_device,
            self.b_private_fence,
            self.b_authority_fence,
            self.b_event,
            self.b_zone_event,
        }


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    async with api_client_for(spatial_world) as client:
        yield client


@pytest.fixture(scope="module")
async def world(api: Api, spatial_world: SpatialWorld) -> Isolation:
    """Give B a private object of every kind, through the API and the enrichment engine."""
    b_site = ok(
        await api.post(
            "/geo/v1/sites",
            json={"name": "Isolation Site B", "position": _point(*CENTRE), "positionSource": "gps"},
            tenant=TENANT_B,
        ),
        201,
    )
    a_site = ok(
        await api.post(
            "/geo/v1/sites",
            json={"name": "Isolation Site A", "position": _point(80.7502, 8.0302), "positionSource": "gps"},
            tenant=TENANT_A,
        ),
        201,
    )
    b_device = str(uuid.uuid4())
    ok(
        await api.put(
            f"/geo/v1/devices/{b_device}/placement",
            json={
                "name": "Isolation Camera B",
                "deviceType": "camera",
                "position": _point(80.7501, 8.0301),
                "positionSource": "gps",
                "siteId": b_site["id"],
                "fieldOfView": {"method": "modelled", "bearingDeg": 180, "fovDeg": 90, "rangeM": 400},
            },
            tenant=TENANT_B,
        ),
        201,
    )
    engine = GeoContextService(spatial_world.app_sessions, spatial_world.service_area, GeoContextLimits())
    for event_id, tenant, position in (
        ("iso-event-b", TENANT_B, CENTRE),  # inside B's private geofence
        ("iso-event-b-zone", TENANT_B, MULTI_ZONE_POINT),  # inside risk zones
        ("iso-event-a", TENANT_A, CENTRE),
    ):
        await engine.enrich(
            EventLocationIn.model_validate(
                {
                    "eventId": event_id,
                    "tenantId": tenant.value,
                    "observedAt": datetime(2026, 9, 12, 6, tzinfo=UTC).isoformat(),
                    "eventType": "wildlife.elephant_detected",
                    "sourceType": "sensor",
                    "locationSource": "sensor",
                    "location": _point(*position),
                }
            ),
            release_code=SYNTHETIC_RELEASE,
        )
    # B reads its own data once, so B has audit entries A must not see.
    ok(await api.get("/geo/v1/geofences", tenant=TENANT_B))
    ops = spatial_world.ops
    return Isolation(
        b_site=b_site["id"],
        b_device=b_device,
        b_private_fence=str(ops.b_private_fence),
        b_authority_fence=str(ops.b_authority_fence),
        b_shared_fence=str(ops.b_shared_fence),
        b_shared_device=str(ops.camera_b2_shared),
        b_event="iso-event-b",
        b_zone_event="iso-event-b-zone",
        a_event="iso-event-a",
        a_site=a_site["id"],
    )


def _ids(collection: dict[str, Any]) -> set[str]:
    items = collection.get("features", collection.get("items", []))
    return {str(item["id"]) for item in items}


# --- the database: row-level security ---------------------------------------------------------------------

_TENANT_TABLES = text(
    """
    SELECT format('%I.%I', n.nspname, c.relname) AS name, c.relrowsecurity AS rls,
           c.relkind::text AS kind, pg_get_userbyid(c.relowner) AS owner,
           a.attnotnull AS tenant_not_null,
           EXISTS (SELECT 1 FROM pg_attribute s WHERE s.attrelid = c.oid AND s.attname = 'sharing_policy'
                   AND NOT s.attisdropped) AS shareable
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
    WHERE n.nspname = ANY(:schemas) AND c.relkind IN ('r', 'p') AND NOT c.relispartition
    ORDER BY 1
    """
)
_POLICY_COMMANDS = text(
    "SELECT array_agg(DISTINCT cmd ORDER BY cmd) FROM pg_policies WHERE schemaname || '.' || tablename = :t"
)


@dataclass(frozen=True, slots=True)
class TenantTable:
    name: str
    rls: bool
    owner: str
    has_tenant: bool
    tenant_not_null: bool
    shareable: bool


async def _tenant_tables(session: AsyncSession) -> list[TenantTable]:
    rows = (await session.execute(_TENANT_TABLES, {"schemas": list(TENANT_SCHEMAS)})).all()
    return [
        TenantTable(
            name=row.name,
            rls=row.rls,
            owner=row.owner,
            has_tenant=row.tenant_not_null is not None,
            tenant_not_null=bool(row.tenant_not_null),
            shareable=row.shareable,
        )
        for row in rows
    ]


def _visible_to_a_anyway(table: TenantTable) -> str:
    """Rows of B that A is allowed to see: those B shared with A (for tables that can be shared)."""
    if table.shareable:
        return "(sharing_policy = 'shared' AND shared_with_tenants @> ARRAY['fixture-tenant-a'])"
    if table.name == "ops.device_field_of_view":
        # A field of view is visible exactly when its device is.
        return (
            "EXISTS (SELECT 1 FROM ops.device d WHERE d.id = device_id AND d.sharing_policy = 'shared' "
            "AND d.shared_with_tenants @> ARRAY['fixture-tenant-a'])"
        )
    return "false"


async def test_every_table_of_tenant_data_carries_the_tenant_and_row_level_security(
    world: Isolation, spatial_world: SpatialWorld
) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        tables = await _tenant_tables(session)
        commands = {
            t.name: (await session.execute(_POLICY_COMMANDS, {"t": t.name})).scalar_one() for t in tables
        }
    assert {t.name for t in tables} >= {
        "ops.site",
        "ops.device",
        "ops.device_field_of_view",
        "ops.geofence",
        "geo.event_location",
        "geo.event_geo_context",
        "geo.event_geofence_hit",
        "geo.event_zone_hit",
        "audit.entry",
    }
    app_user = spatial_world.settings.db_app_user
    for table in tables:
        assert table.has_tenant, f"{table.name} holds tenant data but has no tenant_id"
        assert table.rls, f"{table.name} must be protected by row-level security"
        assert table.owner != app_user, f"the runtime login must not own {table.name} (owners bypass RLS)"
        if table.name == "audit.entry":
            # Entries of platform operations (reference data releases) belong to no tenant.
            assert commands[table.name] == ["INSERT", "SELECT"], "the audit log is append-only"
        else:
            assert table.tenant_not_null, f"{table.name}.tenant_id must be NOT NULL"
            assert commands[table.name] == ["DELETE", "INSERT", "SELECT", "UPDATE"], table.name


async def test_the_runtime_login_cannot_bypass_row_level_security(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.app_sessions) as session:
        flags = (
            await session.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    assert not flags.rolsuper
    assert not flags.rolbypassrls


async def test_tenant_a_sees_no_private_row_of_tenant_b_in_any_table(
    world: Isolation, spatial_world: SpatialWorld
) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        tables = await _tenant_tables(session)
        # Owner's view (no row-level security): B really has private rows in every table.
        stored = {
            t.name: (
                await session.execute(
                    text(  # table names come from the catalogue
                        f"SELECT count(*) FROM {t.name} "  # noqa: S608
                        f"WHERE tenant_id = :b AND NOT {_visible_to_a_anyway(t)}"
                    ),
                    {"b": TENANT_B.value},
                )
            ).scalar_one()
            for t in tables
        }
    assert all(count > 0 for count in stored.values()), f"B must have private rows everywhere: {stored}"

    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        for table in tables:
            leaked = (
                await session.execute(
                    text(
                        f"SELECT count(*) FROM {table.name} "  # noqa: S608
                        f"WHERE tenant_id = :b AND NOT {_visible_to_a_anyway(table)}"
                    ),
                    {"b": TENANT_B.value},
                )
            ).scalar_one()
            assert leaked == 0, f"tenant A sees {leaked} private rows of tenant B in {table.name}"


async def test_without_a_tenant_no_tenant_row_is_visible(
    world: Isolation, spatial_world: SpatialWorld
) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        tables = await _tenant_tables(session)
    async with transaction(spatial_world.app_sessions) as session:
        for table in tables:
            visible = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table.name} WHERE tenant_id IS NOT NULL")  # noqa: S608
                )
            ).scalar_one()
            assert visible == 0, f"{table.name} shows tenant rows to a transaction without a tenant"


async def test_tenant_a_cannot_change_or_delete_rows_of_tenant_b(
    world: Isolation, spatial_world: SpatialWorld
) -> None:
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        for table, object_id in (
            ("ops.geofence", world.b_private_fence),
            ("ops.geofence", world.b_shared_fence),  # shared for reading only
            ("ops.site", world.b_site),
            ("ops.device", world.b_device),
        ):
            changed = await session.execute(
                text(f"UPDATE {table} SET name = 'taken over' WHERE id = :id"),  # noqa: S608
                {"id": object_id},
            )
            assert changed.rowcount == 0, f"A changed B's {table} row"  # type: ignore[attr-defined]
            deleted = await session.execute(
                text(f"DELETE FROM {table} WHERE id = :id"),  # noqa: S608
                {"id": object_id},
            )
            assert deleted.rowcount == 0, f"A deleted B's {table} row"  # type: ignore[attr-defined]
    async with transaction(spatial_world.migrator_sessions) as session:
        names = (
            await session.execute(
                text("SELECT name FROM ops.geofence WHERE id IN (:p, :s)"),
                {"p": world.b_private_fence, "s": world.b_shared_fence},
            )
        ).scalars()
        assert "taken over" not in set(names)


async def test_tenant_a_cannot_write_rows_for_tenant_b(world: Isolation, spatial_world: SpatialWorld) -> None:
    insert_for_b = text(
        "INSERT INTO ops.site (tenant_id, name, geom, position_source) "
        "VALUES (:b, 'planted', public.ST_SetSRID(public.ST_MakePoint(80.75, 8.03), 4326), 'gps')"
    )
    move_to_b = text("UPDATE ops.site SET tenant_id = :b WHERE id = :id")
    for statement, params in (
        (insert_for_b, {"b": TENANT_B.value}),
        (move_to_b, {"b": TENANT_B.value, "id": world.a_site}),
    ):
        with pytest.raises(DBAPIError, match="row-level security"):
            async with transaction(spatial_world.app_sessions, TENANT_A) as session:
                await session.execute(statement, params)


async def test_the_tenant_context_ends_with_the_transaction(spatial_world: SpatialWorld) -> None:
    """A pooled connection never carries one request's tenant into the next."""
    async with spatial_world.app_engine.connect() as connection:
        async with connection.begin():
            await connection.execute(
                text("SELECT set_config('gis.tenant_id', :t, true)"), {"t": TENANT_A.value}
            )
            inside = (await connection.execute(text("SELECT meta.current_tenant_id()"))).scalar_one()
        async with connection.begin():
            after = (await connection.execute(text("SELECT meta.current_tenant_id()"))).scalar_one()
            sites = (await connection.execute(text("SELECT count(*) FROM ops.site"))).scalar_one()
    assert (inside, after, sites) == (TENANT_A.value, None, 0)


# --- the API: tenant from the identity --------------------------------------------------------------------

# Every GET that reads tenant data, with a request that is otherwise valid.
TENANT_READS: Final[tuple[tuple[str, dict[str, str]], ...]] = (
    ("/geo/v1/layers/ops.geofence/features", {}),
    ("/geo/v1/layers/ops.geofence/export", {}),
    ("/geo/v1/geofences", {}),
    ("/geo/v1/sites", {}),
    (EVENTS, WINDOW),
    ("/geo/v1/events/export", WINDOW),
    ("/geo/v1/audit/entries", {}),
)


@pytest.mark.parametrize(("path", "params"), TENANT_READS)
async def test_naming_another_tenant_is_refused(
    api: Api, world: Isolation, path: str, params: dict[str, str]
) -> None:
    as_a = api.headers(TENANT_A)
    response = await api.get(path, params={**params, "tenantId": TENANT_B.value}, headers=as_a)

    problem = assert_problem(response, 403, "forbidden")
    assert problem["tenantId"] == TENANT_B.value


async def test_naming_another_tenant_for_an_object_is_refused(api: Api, world: Isolation) -> None:
    for path in (
        f"/geo/v1/geofences/{world.b_private_fence}",
        f"/geo/v1/sites/{world.b_site}",
        f"/geo/v1/devices/{world.b_device}/placement",
    ):
        response = await api.get(path, params={"tenantId": TENANT_B.value}, tenant=TENANT_A)
        assert_problem(response, 403, "forbidden")


async def test_other_tenant_headers_do_not_select_a_tenant(api: Api, world: Isolation) -> None:
    headers = {**api.headers(TENANT_A), "X-Tenant-Id": TENANT_B.value, "X-Tenant": TENANT_B.value}
    answer = ok(await api.get("/geo/v1/geofences", params={"limit": 1000}, headers=headers))

    assert {item["tenantId"] for item in answer["items"]} <= {TENANT_A.value, TENANT_B.value}
    assert not _ids(answer) & world.private_to_b


async def test_a_tenant_in_a_request_body_must_be_the_one_the_request_acts_for(
    api: Api, world: Isolation
) -> None:
    body = {
        "eventId": "iso-planted",
        "tenantId": TENANT_B.value,
        "observedAt": "2026-09-12T07:00:00Z",
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": _point(*CENTRE),
    }
    response = await api.post("/geo/v1/enrich", json=body, tenant=TENANT_A)

    assert_problem(response, 403, "forbidden")


# --- the API: geofences -----------------------------------------------------------------------------------


async def test_an_object_is_created_for_the_tenant_the_request_acts_for_only(
    api: Api, world: Isolation
) -> None:
    fence = {
        "name": "Isolation Fence A",
        "definition": {"kind": "circle", "geometry": _point(80.72, 7.99), "radiusM": 150},
        "status": "active",
    }
    created = ok(await api.post("/geo/v1/geofences", json=fence, tenant=TENANT_A), 201)
    planted = await api.post("/geo/v1/geofences", json={**fence, "tenantId": TENANT_B.value}, tenant=TENANT_A)

    assert created["tenantId"] == TENANT_A.value
    assert_problem(planted, 422, "request_validation_error")  # a body cannot name a tenant at all


async def test_tenant_a_lists_no_private_geofence_of_tenant_b(api: Api, world: Isolation) -> None:
    listed = _ids(ok(await api.get("/geo/v1/geofences", params={"limit": 1000}, tenant=TENANT_A)))

    assert world.b_shared_fence in listed  # shared with A: the control that B's data is there at all
    assert world.b_private_fence not in listed
    assert world.b_authority_fence not in listed  # shared with authorities only


async def test_tenant_a_cannot_read_a_private_geofence_of_tenant_b_by_its_id(
    api: Api, world: Isolation
) -> None:
    for fence in (world.b_private_fence, world.b_authority_fence):
        response = await api.get(f"/geo/v1/geofences/{fence}", tenant=TENANT_A)
        assert_problem(response, 404, "geofence_not_found")


async def test_an_authority_reads_what_was_shared_with_authorities(api: Api, world: Isolation) -> None:
    """The sharing policies do what they say: the control for the two tests above."""
    listed = _ids(ok(await api.get("/geo/v1/geofences", params={"limit": 1000}, tenant=AUTHORITY)))

    assert {world.b_authority_fence, world.b_shared_fence} <= listed
    assert world.b_private_fence not in listed


async def test_tenant_a_cannot_change_or_delete_a_geofence_of_tenant_b(api: Api, world: Isolation) -> None:
    replacement = {
        "name": "Taken over",
        "definition": {"kind": "circle", "geometry": _point(*CENTRE), "radiusM": 100},
        "status": "active",
        "version": 1,
    }
    shared = f"/geo/v1/geofences/{world.b_shared_fence}"
    assert_problem(await api.put(shared, json=replacement, tenant=TENANT_A), 403, "not_owner")
    assert_problem(await api.delete(shared, tenant=TENANT_A), 403, "not_owner")
    private = f"/geo/v1/geofences/{world.b_private_fence}"
    assert_problem(await api.put(private, json=replacement, tenant=TENANT_A), 404, "geofence_not_found")
    assert_problem(
        await api.delete(private, params={"purge": "true"}, tenant=TENANT_A),
        404,
        "geofence_not_found",
    )
    still = ok(await api.get(private, tenant=TENANT_B))
    assert (still["name"], still["status"]) == ("Fixture B Private Fence", "active")


# --- the API: map data ------------------------------------------------------------------------------------


@pytest.mark.parametrize("layer", OPERATIONAL_LAYERS)
async def test_map_features_of_tenant_a_hold_no_private_object_of_tenant_b(
    api: Api, world: Isolation, layer: str
) -> None:
    answer = ok(
        await api.get(
            f"/geo/v1/layers/{layer}/features",
            params={"bbox": AROUND_CENTRE, "limit": 1000},
            tenant=TENANT_A,
        )
    )
    owners = {feature["properties"].get("tenantId") for feature in answer["features"]}

    assert not _ids(answer) & world.private_to_b
    if layer == "ops.device_field_of_view":
        assert TENANT_B.value not in owners  # B's field of view belongs to its private camera
    for feature in answer["features"]:
        if feature["properties"].get("tenantId") == TENANT_B.value:
            assert feature["properties"].get("sharingPolicy") == "shared", feature


@pytest.mark.parametrize("layer", OPERATIONAL_LAYERS)
async def test_the_same_map_features_show_tenant_b_its_own_objects(
    api: Api, world: Isolation, layer: str
) -> None:
    """The control: B's private objects are in that viewport, so their absence for A means something."""
    answer = ok(
        await api.get(
            f"/geo/v1/layers/{layer}/features",
            params={"bbox": AROUND_CENTRE, "limit": 1000},
            tenant=TENANT_B,
        )
    )

    assert TENANT_B.value in {feature["properties"].get("tenantId") for feature in answer["features"]}


QUESTIONS: Final[tuple[tuple[str, dict[str, Any], str], ...]] = (
    *(
        (operation, extra, layer)
        for operation, extra in (
            ("within-distance", {"distanceM": 5000}),
            ("nearest", {"maxDistanceM": 5000, "limit": 100}),
        )
        for layer in ("ops.geofence", "ops.device", "ops.site")
    ),
    ("contains", {"mode": "intersects"}, "ops.geofence"),  # containment needs a layer with areas
)


@pytest.mark.parametrize(("operation", "extra", "layer"), QUESTIONS)
async def test_spatial_questions_of_tenant_a_find_no_private_object_of_tenant_b(
    api: Api, world: Isolation, operation: str, extra: dict[str, Any], layer: str
) -> None:
    body = {"target": layer, "geometry": _point(*CENTRE), **extra}
    for_a = ok(await api.post(f"/geo/v1/query/{operation}", json=body, tenant=TENANT_A))
    for_b = ok(await api.post(f"/geo/v1/query/{operation}", json=body, tenant=TENANT_B))

    assert _ids(for_b) & world.private_to_b, "the control: B finds its own private objects there"
    assert not _ids(for_a) & world.private_to_b


async def test_exports_of_tenant_a_hold_no_private_object_of_tenant_b(api: Api, world: Isolation) -> None:
    for layer in OPERATIONAL_LAYERS:
        export = ok(await api.get(f"/geo/v1/layers/{layer}/export", tenant=TENANT_A))
        assert export["tenantId"] == TENANT_A.value
        assert not _ids(export) & world.private_to_b, layer


async def test_a_cursor_from_tenant_b_does_not_page_tenant_a(api: Api, world: Isolation) -> None:
    first = ok(await api.get("/geo/v1/layers/ops.geofence/features", params={"limit": 1}, tenant=TENANT_B))
    assert first["nextCursor"] is not None
    response = await api.get(
        "/geo/v1/layers/ops.geofence/features",
        params={"limit": 1, "cursor": first["nextCursor"]},
        tenant=TENANT_A,
    )

    assert_problem(response, 422, "invalid_cursor")


# --- the API: sites and devices ---------------------------------------------------------------------------


async def test_tenant_a_cannot_read_a_site_or_device_of_tenant_b(api: Api, world: Isolation) -> None:
    assert world.b_site not in _ids(
        ok(await api.get("/geo/v1/sites", params={"limit": 1000}, tenant=TENANT_A))
    )
    assert_problem(await api.get(f"/geo/v1/sites/{world.b_site}", tenant=TENANT_A), 404, "site_not_found")
    assert_problem(
        await api.get(f"/geo/v1/devices/{world.b_device}/placement", tenant=TENANT_A),
        404,
        "device_not_found",
    )
    shared = ok(await api.get(f"/geo/v1/devices/{world.b_shared_device}/placement", tenant=TENANT_A))
    assert shared["tenantId"] == TENANT_B.value  # the control: B shared this one with A


async def test_tenant_a_cannot_move_a_device_of_tenant_b(api: Api, world: Isolation) -> None:
    move = {"name": "Moved", "deviceType": "camera", "position": _point(80.72, 7.99), "positionSource": "gps"}
    response = await api.put(f"/geo/v1/devices/{world.b_device}/placement", json=move, tenant=TENANT_A)

    assert response.status_code in (403, 404, 409), response.text
    assert "position" not in response.json()
    placement = ok(await api.get(f"/geo/v1/devices/{world.b_device}/placement", tenant=TENANT_B))
    assert placement["position"]["coordinates"] == [80.7501, 8.0301]


async def test_tenant_a_cannot_change_a_site_of_tenant_b(api: Api, world: Isolation) -> None:
    site = f"/geo/v1/sites/{world.b_site}"
    body = {"name": "Taken over", "position": _point(*CENTRE), "positionSource": "gps", "version": 1}
    assert_problem(await api.put(site, json=body, tenant=TENANT_A), 404, "site_not_found")
    assert_problem(await api.delete(site, tenant=TENANT_A), 404, "site_not_found")


# --- the API: events --------------------------------------------------------------------------------------


async def test_event_queries_of_tenant_a_hold_no_event_of_tenant_b(api: Api, world: Isolation) -> None:
    for_a = _ids(ok(await api.get(EVENTS, params={**WINDOW, "bbox": AROUND_CENTRE}, tenant=TENANT_A)))
    for_b = _ids(ok(await api.get(EVENTS, params={**WINDOW, "bbox": AROUND_CENTRE}, tenant=TENANT_B)))

    assert world.a_event in for_a
    assert world.b_event in for_b
    assert world.b_event not in for_a


async def test_a_geofence_of_tenant_b_does_not_select_its_events_for_tenant_a(
    api: Api, world: Isolation
) -> None:
    by_fence = {**WINDOW, "geofenceId": world.b_private_fence}
    for_b = _ids(ok(await api.get(EVENTS, params=by_fence, tenant=TENANT_B)))
    for_a = _ids(ok(await api.get(EVENTS, params=by_fence, tenant=TENANT_A)))

    assert world.b_event in for_b  # the control: B's event was found in B's private fence
    assert for_a == set()


async def test_event_exports_of_tenant_a_hold_no_event_of_tenant_b(api: Api, world: Isolation) -> None:
    export = ok(await api.get("/geo/v1/events/export", params=WINDOW, tenant=TENANT_A))

    assert world.a_event in _ids(export)
    assert world.b_event not in _ids(export)


async def test_the_geo_context_of_tenant_a_names_no_private_geofence_of_tenant_b(
    api: Api, world: Isolation
) -> None:
    body = {
        "eventId": "iso-context-a",
        "tenantId": TENANT_A.value,
        "observedAt": "2026-09-12T08:00:00Z",
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": _point(*CENTRE),
    }
    context = ok(
        await api.post(
            "/geo/v1/enrich",
            params={"refDataRelease": SYNTHETIC_RELEASE},
            json=body,
            tenant=TENANT_A,
        )
    )
    hits = {hit["id"] for hit in context["geofenceHits"]}
    devices = {device["deviceId"] for device in context["nearestDevices"]}

    assert not hits & {world.b_private_fence, world.b_authority_fence}
    assert world.b_device not in devices


# --- the API: the audit log -------------------------------------------------------------------------------


async def test_tenant_a_reads_no_audit_entry_of_tenant_b(api: Api, world: Isolation) -> None:
    entries = ok(await api.get("/geo/v1/audit/entries", params={"limit": 1000}, tenant=TENANT_A))
    of_b = ok(await api.get("/geo/v1/audit/entries", params={"limit": 1000}, tenant=TENANT_B))

    assert of_b["count"] > 0
    assert {entry["tenantId"] for entry in entries["items"]} == {TENANT_A.value}


# --- coverage ---------------------------------------------------------------------------------------------

COVERED_OPERATIONS: Final = frozenset(
    {
        "listLayerFeatures",
        "exportLayerFeatures",
        "queryWithinDistance",
        "queryNearest",
        "queryContains",
        "listEvents",
        "exportEvents",
        "listGeofences",
        "createGeofence",  # through the world fixture: B's objects are created as B
        "getGeofence",
        "replaceGeofence",
        "deleteGeofence",
        "listSites",
        "createSite",
        "getSite",
        "replaceSite",
        "deleteSite",
        "getDevicePlacement",
        "putDevicePlacement",
        "enrichEvent",
        "listAuditEntries",
    }
)
# Operations that read or change no tenant data.
TENANT_FREE_OPERATIONS: Final = frozenset(
    {"listLayers", "reverseGeocode", "getIdentity", "listReleases", "getRelease"}
)


async def test_every_tenant_data_endpoint_is_covered(api: Api) -> None:
    """A new endpoint that takes a tenant must be added to this suite (or declared tenant-free)."""
    document = (await api.client.get("/openapi.json")).json()
    operations = {
        operation["operationId"]
        for operations in document["paths"].values()
        for operation in operations.values()
        if "x-gis-permissions" in operation
    }

    assert operations - TENANT_FREE_OPERATIONS == COVERED_OPERATIONS
