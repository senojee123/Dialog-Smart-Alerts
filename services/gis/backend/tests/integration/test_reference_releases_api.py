"""The release catalogue, attribution and licence-aware exports through the API.

``GET /geo/v1/releases`` answers where reference data comes from; the layer catalogue carries the
attribution the licences require; an export of data whose licence does not allow redistribution is
refused. The last test publishes a release of its own and puts the fixture release back afterwards.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.db.session import transaction
from app.services.reference_loader import ReferenceDataLoader
from app.services.reference_releases import ReleaseManager
from tests.integration.api_client import Api, api_client_for, assert_problem, ok
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import OPEN_MANIFEST, OPEN_RELEASE, SYNTHETIC_RELEASE

RELEASES = "/geo/v1/releases"
LAYERS = "/geo/v1/layers"
OSM = "© OpenStreetMap contributors"


@pytest.fixture(scope="module")
async def api(spatial_world: SpatialWorld) -> AsyncIterator[Api]:
    async with api_client_for(spatial_world) as client:
        yield client


async def test_published_releases_are_listed_the_current_one_first(api: Api) -> None:
    body = ok(await api.get(RELEASES))
    codes = [item["code"] for item in body["releases"]]
    assert codes[0] == OPEN_RELEASE
    assert set(codes) >= {OPEN_RELEASE, SYNTHETIC_RELEASE}
    current = body["releases"][0]
    assert current["isCurrent"] is True
    assert (current["status"], current["purpose"], current["datasets"]) == ("published", "test", 7)
    assert current["features"] == 141


async def test_a_release_names_the_lineage_and_licence_of_every_dataset(api: Api) -> None:
    body = ok(await api.get(f"{RELEASES}/{OPEN_RELEASE}"))
    lineage = body["datasetLineage"]
    assert len(lineage) == 7
    manifest = json.loads(OPEN_MANIFEST.read_text(encoding="utf-8"))
    licences = {source["code"]: source["licence"] for source in manifest["sources"]}
    for dataset in lineage:
        assert dataset["licence"] == licences[dataset["source"]]
        for member in (
            "sourceReference",
            "sourceVersion",
            "importedAt",
            "sourceCrs",
            "geometryAccuracyM",
            "attribution",
        ):
            assert dataset[member], (dataset["sourceFile"], member)
        assert dataset["geometryTypes"]
        assert dataset["storageCrs"] == "EPSG:4326"
    assert body["qa"]["status"] in ("passed", "warnings")
    assert any(OSM in statement for statement in body["attribution"])


async def test_an_unknown_release_is_not_found(api: Api) -> None:
    assert_problem(await api.get(f"{RELEASES}/ref-2001.01"), 404, "release_not_found")


async def test_releases_need_no_credentials(api: Api) -> None:
    ok(await api.client.get(RELEASES))


async def test_the_catalogue_carries_the_attribution_of_each_layer(api: Api) -> None:
    body = ok(await api.get(LAYERS))
    assert body["refDataRelease"] == OPEN_RELEASE
    layers = {item["code"]: item for item in body["layers"]}
    assert layers["ref.road"]["attribution"] == ["Made with Natural Earth"]
    assert any(OSM in statement for statement in layers["ref.admin_area"]["attribution"])
    assert layers["ref.road"]["exportable"] is True
    # Operational layers are the tenant's own data: no third-party attribution.
    assert layers["ops.geofence"]["attribution"] == []
    # Every attribution a layer needs is also in the catalogue's list, once.
    everything = body["attribution"]
    assert len(everything) == len(set(everything))
    for layer in layers.values():
        for statement in layer["attribution"]:
            assert any(statement in listed for listed in everything)


async def test_data_whose_licence_forbids_redistribution_is_not_exported(
    api: Api, spatial_world: SpatialWorld, tmp_path: Path
) -> None:
    manifest = json.loads(OPEN_MANIFEST.read_text(encoding="utf-8"))
    roads = next(item for item in manifest["files"] if item["layer"] == "ref.road")
    source = next(item for item in manifest["sources"] if item["code"] == roads["source"])
    restricted = {**source, "code": "roads-no-redistribution", "redistributionAllowed": False}
    shutil.copyfile(OPEN_MANIFEST.parent / roads["path"], tmp_path / roads["path"])
    manifest.update(sources=[restricted], files=[{**roads, "source": restricted["code"]}])
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    code = "ref-2026.09-restricted"
    async with transaction(spatial_world.migrator_sessions) as session:
        await ReferenceDataLoader(session, spatial_world.service_area).load(
            tmp_path / "manifest.json", release_code=code, publish=True, make_current=True
        )
    try:
        export = f"{LAYERS}/ref.road/export"
        problem = assert_problem(await api.get(export), 403, "export_not_permitted")
        assert problem["sources"] == ["roads-no-redistribution"]
        assert problem["refDataRelease"] == code
        layers = {item["code"]: item for item in ok(await api.get(LAYERS))["layers"]}
        assert layers["ref.road"]["exportable"] is False
        # Reading the data on the map is still allowed; only letting it leave the platform is not.
        ok(await api.get(f"{LAYERS}/ref.road/features", params={"bbox": "80.6,7.9,80.9,8.2"}))
    finally:
        async with transaction(spatial_world.migrator_sessions) as session:
            manager = ReleaseManager(session)
            await manager.make_current(OPEN_RELEASE)
            await manager.retire(code)
