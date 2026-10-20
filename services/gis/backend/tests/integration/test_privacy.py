"""Privacy: the GIS service keeps no personal notification locations, tracks no recipients, and stores no
more personal location information than its purpose needs.

Checked against the migrated catalogue, so a migration that adds such a thing fails here:

* no table or column is about people as recipients or contacts - no recipient, subscriber, notification,
  contact, phone or e-mail data, no home or user location;
* the only columns that identify a person hold the identity provider's opaque subject id (``created_by``,
  ``updated_by``, the audit log's actor), never a name or an address, and the API writes them that way;
* every geometry column belongs to a reviewed table - reference data, operational objects, event locations,
  and the audit log's coarse extent. A new geometry column is a privacy decision and must be added here
  deliberately;
* the audit log's location detail is a 0.001 degree cell at best.
"""

from __future__ import annotations

import random
import re
from collections.abc import AsyncIterator
from typing import Final

import pytest
from sqlalchemy import text

from app.core.caller import PLATFORM_SUBJECT
from app.db.base import APPLICATION_SCHEMAS
from app.db.session import transaction
from tests.integration.api_client import Api, api_client_for, ok
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import TENANT_A, TENANT_B

PERSONAL: Final = re.compile(
    r"recipient|subscri|notif|contact|phone|msisdn|e_?mail|person|citizen|resident|next_of_kin|mobile"
    r"|home|address|user_?loc|user_?pos|tracking|watcher|follower"
)
# Columns that say who did something: opaque subject ids (and database logins), never names.
IDENTITY_COLUMNS: Final = frozenset(
    {
        "audit.entry.actor_subject",
        "audit.entry.actor_client",
        "audit.entry.db_user",
        "meta.dataset_load.loaded_by",
        "meta.dataset_lineage.loaded_by",
        "meta.ref_data_release.created_by",
        # Reference data pipeline (revision 20260924_0008): database logins, the waiver's actor (subject id
        # from gis.actor_subject), and the role that reviewed a licence (documented as a role, not a name).
        "meta.qa_run.run_by",
        "meta.qa_finding.waived_by",
        "meta.release_artifact.created_by",
        "meta.data_source.licence_reviewed_by",
        *(
            f"ops.{table}.{column}"
            for table in ("site", "device", "device_field_of_view", "geofence")
            for column in ("created_by", "updated_by")
        ),
    }
)
# Tables that may hold geometry, and why. Nothing here locates a person.
GEOMETRY_TABLES: Final = {
    "audit.entry": "coarse extent of a search or change (0.001 degree grid)",
    "geo.event_location": "where a device or sensor observed an event",
    "meta.geometry_repair": "reference geometry before the loader repaired it",
    "meta.dataset_load": "bounding box of a reference dataset",
    "meta.dataset_lineage": "bounding box of a reference dataset (view of meta.dataset_load)",
    "meta.qa_finding": "where a reference data QA check found a problem",
    "meta.release_artifact": "bounds of a basemap built for a release",
    "ops.device": "where a camera or sensor is installed",
    "ops.device_field_of_view": "the area a device observes",
    "ops.geofence": "areas a tenant maintains",
    "ops.site": "fixed installations",
    **{
        f"ref.{table}": "national reference data"
        for table in (
            "admin_area",
            "area_part",
            "facility",
            "protected_area",
            "risk_zone",
            "road",
            "settlement",
            "water_body",
        )
    },
}

_COLUMNS = text(
    """
    SELECT c.table_schema || '.' || c.table_name AS table_name, c.column_name
    FROM information_schema.columns c
    WHERE c.table_schema = ANY(:schemas) AND c.table_name !~ '_p[0-9]{6}$'
    """
)
_GEOMETRY = text(
    """
    SELECT DISTINCT f_table_schema || '.' || f_table_name
    FROM public.geometry_columns
    WHERE f_table_schema = ANY(:schemas) AND f_table_name !~ '_p[0-9]{6}$'
    """
)


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    async with api_client_for(spatial_world) as client:
        yield client


async def test_nothing_in_the_schema_is_about_people_as_recipients_or_contacts(
    spatial_world: SpatialWorld,
) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        columns = (await session.execute(_COLUMNS, {"schemas": list(APPLICATION_SCHEMAS)})).all()
    names = {row.table_name for row in columns} | {f"{row.table_name}.{row.column_name}" for row in columns}

    assert sorted(name for name in names if PERSONAL.search(name)) == []


async def test_the_only_identity_columns_hold_subject_ids(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        columns = (await session.execute(_COLUMNS, {"schemas": list(APPLICATION_SCHEMAS)})).all()
    identity = {
        f"{row.table_name}.{row.column_name}"
        for row in columns
        if re.search(
            r"(_by|actor_subject|actor_client|db_user|username|user_id|owner_name)$", row.column_name
        )
    }

    assert identity == IDENTITY_COLUMNS


async def test_objects_record_the_platform_as_their_author(api: Api) -> None:
    """The main platform owns users; the GIS records who acted as the platform, never a person's details."""
    site = ok(
        await api.post(
            "/geo/v1/sites",
            json={
                "name": "Privacy Site",
                "position": {"type": "Point", "coordinates": [80.72, 7.99]},
                "positionSource": "gps",
            },
            tenant=TENANT_A,
        ),
        201,
    )

    assert site["createdBy"] == PLATFORM_SUBJECT


async def test_a_shared_object_does_not_reveal_who_in_the_owning_tenant_edited_it(api: Api) -> None:
    fence = {
        "name": "Privacy Shared Fence",
        "definition": {
            "kind": "circle",
            "geometry": {"type": "Point", "coordinates": [80.72, 7.99]},
            "radiusM": 90,
        },
        "status": "active",
        "sharingPolicy": "shared",
        "sharedWithTenants": [TENANT_A.value],
    }
    shared = ok(await api.post("/geo/v1/geofences", json=fence, tenant=TENANT_B), 201)["id"]
    for_owner = ok(await api.get(f"/geo/v1/geofences/{shared}", tenant=TENANT_B))
    for_reader = ok(await api.get(f"/geo/v1/geofences/{shared}", tenant=TENANT_A))
    listed = ok(await api.get("/geo/v1/geofences", params={"limit": 1000}, tenant=TENANT_A))

    assert for_owner["createdBy"] == PLATFORM_SUBJECT
    assert (for_reader["createdBy"], for_reader["updatedBy"]) == (None, None)
    assert all(item["createdBy"] is None for item in listed["items"] if item["tenantId"] != TENANT_A.value)


async def test_only_reviewed_tables_hold_geometry(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        tables = set((await session.execute(_GEOMETRY, {"schemas": list(APPLICATION_SCHEMAS)})).scalars())

    assert tables == set(GEOMETRY_TABLES), "a new geometry column is a privacy decision: review and list it"


async def test_the_audit_log_keeps_a_location_no_finer_than_a_0_001_degree_cell(
    spatial_world: SpatialWorld,
) -> None:
    generator = random.Random(20260923)  # noqa: S311 - reproducible sample points, not a secret
    points = [(generator.uniform(79.7, 81.9), generator.uniform(5.9, 9.8)) for _ in range(200)]
    async with transaction(spatial_world.app_sessions) as session:
        for lon, lat in points:
            box = (
                await session.execute(
                    text(
                        "SELECT public.ST_XMin(e), public.ST_YMin(e), public.ST_XMax(e), public.ST_YMax(e) "
                        "FROM audit.coarse_extent(public.ST_SetSRID(public.ST_MakePoint(:x, :y), 4326)) AS e"
                    ),
                    {"x": lon, "y": lat},
                )
            ).one()
            min_x, min_y, max_x, max_y = box
            assert min_x <= lon <= max_x
            assert min_y <= lat <= max_y
            assert max_x - min_x == pytest.approx(0.001, abs=1e-9)
            assert max_y - min_y == pytest.approx(0.001, abs=1e-9)
            assert round(min_x * 1000) == pytest.approx(min_x * 1000, abs=1e-6)
            assert round(min_y * 1000) == pytest.approx(min_y * 1000, abs=1e-6)


async def test_the_api_takes_and_returns_no_personal_contact_data(api: Api) -> None:
    document = (await api.client.get("/openapi.json")).json()
    members = {
        name for schema in document["components"]["schemas"].values() for name in schema.get("properties", {})
    }
    parameters = {
        parameter["name"]
        for operations in document["paths"].values()
        for operation in operations.values()
        for parameter in operation.get("parameters", [])
    }

    assert sorted(name for name in members | parameters if PERSONAL.search(name.lower())) == []
