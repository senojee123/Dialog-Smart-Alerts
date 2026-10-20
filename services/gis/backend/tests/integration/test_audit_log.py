"""The audit log: what is recorded, by whom it is said to be done, and that it cannot be rewritten.

Checked against the real database and application:

* searches, sensitive queries (reads of operational data and events) and exports are recorded in the
  transaction that answers them - with the caller and request id, the tenant, the operation, the parameters
  and the result count - and an answer is not given if its entry cannot be written;
* geofence creation, change, archiving and purging are recorded by the database, whoever makes them, and
  so are reference data releases (through the loader, with its operator);
* who and for which tenant is stamped by the database: a writer cannot put another actor or tenant in;
* the log is append-only for every login, and each tenant reads only its own entries;
* location detail is coarse (0.001 degree).

Requests come from the main platform (subject ``platform``), which owns sign-in; see ``app.core.caller``.
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from typing import Any, Final

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.caller import PLATFORM_SUBJECT
from app.core.config import get_settings
from app.db.session import transaction
from app.tools import load_reference_data
from tests.integration.api_client import Api, api_client_for, assert_problem, ok
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import (
    CENTRE,
    SYNTHETIC_MANIFEST,
    SYNTHETIC_RELEASE,
    TENANT_A,
    TENANT_B,
)

ENTRIES: Final = "/geo/v1/audit/entries"
# A position with more precision than the log keeps (1e-7 degrees, about 1 cm).
EXACT: Final = (80.7512345, 8.0298765)


def _point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    async with api_client_for(spatial_world) as client:
        yield client


async def _entries(api: Api, tenant: Any = TENANT_A, **params: Any) -> list[dict[str, Any]]:
    answer = ok(await api.get(ENTRIES, params={"limit": 1000, **params}, tenant=tenant))
    items: list[dict[str, Any]] = answer["items"]
    return items


async def _last(api: Api, operation: str, tenant: Any = TENANT_A) -> dict[str, Any]:
    entries = await _entries(api, tenant, operation=operation)
    assert entries, f"no {operation} entry"
    return entries[0]  # newest first


# --- searches and sensitive queries -----------------------------------------------------------------------


async def test_a_spatial_search_is_recorded_with_who_what_where_and_how_many(api: Api) -> None:
    response = await api.post(
        "/geo/v1/query/within-distance",
        json={"target": "ops.device", "geometry": _point(*EXACT), "distanceM": 750},
        tenant=TENANT_A,
    )
    answer = ok(response)

    entry = await _last(api, "query.within_distance")
    assert entry["category"] == "search"
    assert entry["tenantId"] == TENANT_A.value
    assert entry["actor"] == {"subject": PLATFORM_SUBJECT, "clientId": None}
    assert entry["requestId"] == response.headers["x-request-id"]
    assert entry["channel"] == "api"
    assert entry["crossTenant"] is False
    assert entry["target"] == "ops.device"
    assert entry["parameters"]["distanceM"] == 750
    assert entry["resultCount"] == answer["count"]
    assert entry["geometryType"] == "POINT"
    # Only the 0.001 degree cell the point lies in is kept, not the point.
    assert entry["geometryExtent"]["coordinates"] == [
        [[80.751, 8.029], [80.751, 8.03], [80.752, 8.03], [80.752, 8.029], [80.751, 8.029]]
    ]


async def test_the_exact_position_of_a_search_is_not_stored_anywhere(
    api: Api, spatial_world: SpatialWorld
) -> None:
    ok(await api.get("/geo/v1/reverse", params={"lon": EXACT[0], "lat": EXACT[1]}, tenant=TENANT_A))

    async with transaction(spatial_world.migrator_sessions) as session:
        stored = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit.entry WHERE parameters::text LIKE '%80.7512345%' "
                    "OR public.ST_AsText(geometry_extent) LIKE '%80.7512345%'"
                )
            )
        ).scalar_one()
    assert stored == 0
    assert (await _last(api, "query.reverse_geocode"))["geometryType"] == "POINT"


async def test_reading_operational_layers_and_events_is_recorded(api: Api) -> None:
    ok(
        await api.get(
            "/geo/v1/layers/ops.geofence/features", params={"bbox": "80.7,7.9,80.8,8.1"}, tenant=TENANT_A
        )
    )
    ok(await api.get("/geo/v1/events", params={"eventType": "wildlife.elephant_detected"}, tenant=TENANT_A))
    ok(await api.get("/geo/v1/geofences", params={"status": "active"}, tenant=TENANT_A))

    features = await _last(api, "features.list")
    events = await _last(api, "events.list")
    geofences = await _last(api, "geofences.list")
    assert (features["category"], features["target"]) == ("sensitive_query", "ops.geofence")
    assert features["geometryType"] == "POLYGON"  # the viewport
    assert events["category"] == "sensitive_query"
    assert events["parameters"]["filters"] == {"eventType": "wildlife.elephant_detected"}
    assert {"from", "to"} <= set(events["parameters"])
    assert geofences["parameters"]["status"] == "active"


READS: Final[tuple[tuple[str, str, dict[str, Any] | None, str], ...]] = (
    ("GET", "/geo/v1/layers/ops.device/features", None, "features.list"),
    (
        "POST",
        "/geo/v1/query/within-distance",
        {"target": "ops.site", "distanceM": 100},
        "query.within_distance",
    ),
    ("POST", "/geo/v1/query/nearest", {"target": "ref.settlement"}, "query.nearest"),
    ("POST", "/geo/v1/query/contains", {"target": "ref.admin_area"}, "query.contains"),
    ("GET", "/geo/v1/reverse", None, "query.reverse_geocode"),
    ("GET", "/geo/v1/events", None, "events.list"),
    ("GET", "/geo/v1/geofences", None, "geofences.list"),
    ("GET", "/geo/v1/geofences/{circle_fence}", None, "geofence.read"),
    ("GET", "/geo/v1/sites", None, "sites.list"),
    ("GET", "/geo/v1/sites/{site_a1}", None, "site.read"),
    ("GET", "/geo/v1/devices/{camera_a1}/placement", None, "device_placement.read"),
    ("GET", "/geo/v1/layers/ops.geofence/export", None, "export.features"),
    ("GET", "/geo/v1/events/export", None, "export.events"),
    ("GET", ENTRIES, None, "audit.list"),
)


@pytest.mark.parametrize(("method", "path", "body", "operation"), READS)
async def test_every_search_and_read_of_tenant_data_is_recorded(
    api: Api, spatial_world: SpatialWorld, method: str, path: str, body: dict[str, Any] | None, operation: str
) -> None:
    ops = spatial_world.ops
    url = path.format(circle_fence=ops.circle_fence, site_a1=ops.site_a1, camera_a1=ops.camera_a1)
    params = {"lon": CENTRE[0], "lat": CENTRE[1]} if "reverse" in path else None
    json_body = None if body is None else {**body, "geometry": _point(*CENTRE)}
    before = len(await _entries(api, operation=operation))
    response = await api.request(method, url, params=params, json=json_body, tenant=TENANT_A)
    ok(response)

    entries = await _entries(api, operation=operation)
    assert len(entries) == before + (2 if operation == "audit.list" else 1)
    # For the log itself, the earlier read by _entries is the other new entry; this request is the newest.
    newest = entries[0]
    assert newest["actor"]["subject"] == PLATFORM_SUBJECT
    assert newest["requestId"] == response.headers["x-request-id"]


async def test_browsing_reference_data_is_not_recorded_but_searching_it_by_name_is(api: Api) -> None:
    before = len(await _entries(api, operation="features.list"))
    ok(
        await api.get(
            "/geo/v1/layers/ref.settlement/features",
            params={"bbox": "80.7,7.9,80.8,8.1"},
            tenant=TENANT_A,
        )
    )
    after_browsing = len(await _entries(api, operation="features.list"))
    ok(
        await api.get(
            "/geo/v1/layers/ref.settlement/features", params={"nameContains": "Town"}, tenant=TENANT_A
        )
    )
    searched = await _last(api, "features.list")

    assert after_browsing == before
    assert (searched["category"], searched["target"]) == ("search", "ref.settlement")
    assert searched["parameters"]["nameContains"] == "Town"


async def test_an_export_is_recorded_with_what_left_the_service(api: Api) -> None:
    export = ok(await api.get("/geo/v1/layers/ops.site/export", tenant=TENANT_A))

    entry = await _last(api, "export.features")
    assert (entry["category"], entry["target"], entry["resultCount"]) == (
        "export",
        "ops.site",
        export["count"],
    )
    assert entry["parameters"]["format"] == "geojson"


async def test_an_answer_is_not_given_if_its_audit_entry_cannot_be_written(
    api: Api, spatial_world: SpatialWorld
) -> None:
    """Fail closed: without the entry, no data leaves the service."""
    app_user = spatial_world.settings.db_app_user
    async with transaction(spatial_world.migrator_sessions) as session:
        await session.execute(text(f'REVOKE INSERT ON audit.entry FROM "{app_user}"'))
    try:
        response = await api.get("/geo/v1/geofences", tenant=TENANT_A)
    finally:
        async with transaction(spatial_world.migrator_sessions) as session:
            await session.execute(text(f'GRANT INSERT ON audit.entry TO "{app_user}"'))

    assert response.status_code == 500
    assert "items" not in response.text


# --- changes ----------------------------------------------------------------------------------------------


async def test_the_life_of_a_geofence_is_recorded(api: Api) -> None:
    as_a = api.headers(TENANT_A)
    fence: dict[str, Any] = {
        "name": "Audited Fence",
        "definition": {"kind": "circle", "geometry": _point(80.72, 7.99), "radiusM": 200},
        "status": "active",
    }
    created = ok(await api.client.post("/geo/v1/geofences", json=fence, headers=as_a), 201)
    path = f"/geo/v1/geofences/{created['id']}"
    moved = {**fence, "definition": {**fence["definition"], "radiusM": 300}, "version": created["version"]}
    ok(await api.client.put(path, json=moved, headers=as_a))
    assert (await api.client.delete(path, headers=as_a)).status_code == 204
    purge = await api.delete(path, params={"purge": "true"}, tenant=TENANT_A)
    assert purge.status_code == 204

    history = [e for e in await _entries(api, category="change") if e["objectId"] == created["id"]]
    assert [e["operation"] for e in reversed(history)] == [
        "geofence.create",
        "geofence.update",
        "geofence.archive",
        "geofence.purge",
    ]
    create, update, archive, _purged = reversed(history)
    assert {e["actor"]["subject"] for e in history} == {PLATFORM_SUBJECT}
    assert (create["parameters"]["kind"], create["parameters"]["radiusM"]) == ("circle", 200)
    assert update["parameters"]["geometryChanged"] is True
    assert (update["parameters"]["previousVersion"], update["parameters"]["version"]) == (1, 2)
    assert (archive["parameters"]["previousStatus"], archive["parameters"]["status"]) == (
        "active",
        "archived",
    )
    assert all(e["target"] == "ops.geofence" and e["tenantId"] == TENANT_A.value for e in history)
    assert create["geometryType"] == "MULTIPOLYGON"


async def test_a_change_made_directly_in_the_database_is_recorded_too(
    api: Api, spatial_world: SpatialWorld
) -> None:
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        await session.execute(
            text("UPDATE ops.geofence SET description = 'edited by hand' WHERE id = :id"),
            {"id": spatial_world.ops.polygon_fence},
        )

    entry = await _last(api, "geofence.update")
    assert entry["objectId"] == str(spatial_world.ops.polygon_fence)
    assert (entry["channel"], entry["actor"]["subject"]) == ("database", spatial_world.settings.db_app_user)


async def test_a_writer_cannot_choose_the_actor_or_the_tenant_of_an_entry(
    api: Api, spatial_world: SpatialWorld
) -> None:
    async with transaction(spatial_world.app_sessions, TENANT_A) as session:
        await session.execute(
            text(
                "INSERT INTO audit.entry "
                "(category, operation, tenant_id, actor_subject, channel, occurred_at) "
                "VALUES ('search', 'test.forged', :b, 'someone-else', 'api', '2000-01-01')"
            ),
            {"b": TENANT_B.value},
        )

    forged = await _last(api, "test.forged")
    assert forged["tenantId"] == TENANT_A.value
    assert forged["actor"]["subject"] == spatial_world.settings.db_app_user
    assert forged["channel"] == "database"
    assert forged["occurredAt"] > "2026"
    assert await _entries(api, TENANT_B, operation="test.forged") == []


async def test_publishing_a_reference_data_release_is_recorded_with_its_operator(
    api: Api, spatial_world: SpatialWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = spatial_world.settings
    for name, value in {
        "GIS_DB_HOST": settings.db_host,
        "GIS_DB_PORT": str(settings.db_port),
        "GIS_DB_NAME": settings.db_name,
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        result = await load_reference_data.run(
            argparse.Namespace(
                manifest=SYNTHETIC_MANIFEST,
                release="ref-2026.09-audited",
                publish=True,
                current=False,
                actor="data-steward-2",
            )
        )
    finally:
        get_settings.cache_clear()
    assert result.published

    # Release entries belong to no tenant, so no request reads them through the API: read the table.
    async with transaction(spatial_world.migrator_sessions) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT operation, actor_subject, channel, tenant_id, result_count FROM audit.entry "
                    "WHERE category = 'release' AND parameters->>'code' = 'ref-2026.09-audited' ORDER BY id"
                )
            )
        ).all()
    assert [row.operation for row in rows] == ["reference_release.create", "reference_release.publish"]
    published = rows[-1]
    assert (published.actor_subject, published.channel, published.tenant_id) == (
        "data-steward-2",
        "loader",
        None,
    )
    assert published.result_count == sum(item.loaded for item in result.files)


async def test_a_change_made_by_the_database_owner_is_filed_under_the_owning_tenant(
    api: Api, spatial_world: SpatialWorld
) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        await session.execute(
            text("UPDATE ops.site SET name = 'Renamed by an administrator' WHERE id = :id"),
            {"id": spatial_world.ops.site_a1},
        )

    entry = await _last(api, "site.update")
    assert entry["objectId"] == str(spatial_world.ops.site_a1)
    assert entry["tenantId"] == TENANT_A.value
    assert (entry["channel"], entry["actor"]["subject"]) == (
        "database",
        spatial_world.settings.db_migrator_user,
    )


async def test_enriching_an_event_is_recorded_because_it_reveals_operational_data(api: Api) -> None:
    event = {
        "eventId": "audit-enrich-1",
        "tenantId": TENANT_A.value,
        "observedAt": "2026-09-12T09:00:00Z",
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": _point(*EXACT),
    }
    context = ok(
        await api.post(
            "/geo/v1/enrich", params={"refDataRelease": SYNTHETIC_RELEASE}, json=event, tenant=TENANT_A
        )
    )

    entry = await _last(api, "events.enrich")
    assert (entry["objectId"], entry["actor"]["subject"]) == ("audit-enrich-1", PLATFORM_SUBJECT)
    assert entry["crossTenant"] is False
    assert entry["parameters"]["geofenceHits"] == len(context["geofenceHits"])
    assert entry["parameters"]["nearbyDevices"] == len(context["nearestDevices"])
    assert entry["resultCount"] == len(context["geofenceHits"]) + len(context["nearestDevices"])
    assert "80.7512345" not in str(entry)


# --- the log itself ---------------------------------------------------------------------------------------


async def test_entries_cannot_be_changed_or_removed_by_any_login(spatial_world: SpatialWorld) -> None:
    for sessions, error in (
        (spatial_world.app_sessions, "permission denied"),
        (spatial_world.migrator_sessions, "append-only"),
    ):
        for statement in (
            "UPDATE audit.entry SET operation = 'x.y'",
            "DELETE FROM audit.entry",
            "TRUNCATE audit.entry",
        ):
            with pytest.raises(DBAPIError, match=error):
                async with transaction(sessions, TENANT_A) as session:
                    await session.execute(text(statement))


async def test_a_tenant_reads_only_its_own_log(api: Api) -> None:
    ok(await api.get("/geo/v1/geofences", tenant=TENANT_B))

    of_a = await _entries(api, TENANT_A)
    of_b = await _entries(api, TENANT_B)
    assert {e["tenantId"] for e in of_a} == {TENANT_A.value}
    assert {e["tenantId"] for e in of_b} == {TENANT_B.value}


async def test_reading_the_log_is_itself_recorded(api: Api) -> None:
    response = await api.get(ENTRIES, tenant=TENANT_A)
    ok(response)
    read = await _last(api, "audit.list")
    assert read["requestId"] == response.headers["x-request-id"]


async def test_the_log_of_another_tenant_cannot_be_named(api: Api) -> None:
    response = await api.get(ENTRIES, params={"tenantId": TENANT_B.value}, tenant=TENANT_A)
    assert_problem(response, 403, "forbidden")


async def test_entries_are_paged_newest_first(api: Api) -> None:
    for _ in range(3):
        ok(await api.get("/geo/v1/sites", tenant=TENANT_A))
    first = ok(await api.get(ENTRIES, params={"operation": "sites.list", "limit": 2}, tenant=TENANT_A))
    second = ok(
        await api.get(
            ENTRIES,
            params={"operation": "sites.list", "limit": 2, "cursor": first["nextCursor"]},
            tenant=TENANT_A,
        )
    )

    ids = [e["id"] for e in first["items"]] + [e["id"] for e in second["items"]]
    assert len(ids) == len(set(ids)) >= 3
    assert ids == sorted(ids, reverse=True)
