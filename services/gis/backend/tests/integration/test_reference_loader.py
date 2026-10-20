"""Reference data loading: lineage, hierarchy linking, rejection and repair accounting, release rules."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import transaction
from app.services.reference_loader import FileResult, ReferenceDataLoader, ReferenceLoadError
from tests.integration.conftest import SpatialWorld, run_alembic
from tests.integration.spatial_world import OPEN_MANIFEST, SYNTHETIC_MANIFEST, SYNTHETIC_RELEASE


def by_path(files: list[FileResult]) -> dict[str, FileResult]:
    return {item.path: item for item in files}


async def test_open_data_is_loaded_completely(spatial_world: SpatialWorld) -> None:
    result = spatial_world.open_data
    assert result.published
    assert result.current
    files = by_path(result.files)
    assert {path: item.loaded for path, item in files.items()} == {
        "admin_areas_level1.geojson": 9,
        "admin_areas_level2.geojson": 25,
        "admin_areas_level3_pilot.geojson": 29,
        "admin_areas_level4_palugaswewa.geojson": 16,
        "settlements.geojson": 14,
        "roads.geojson": 41,
        "water_bodies.geojson": 7,
    }
    assert all(item.rejected == 0 and item.repaired == 0 for item in result.files)


async def test_synthetic_world_rejections_and_repairs_are_accounted(spatial_world: SpatialWorld) -> None:
    files = by_path(spatial_world.synthetic.files)
    facilities = files["facilities.geojson"]
    assert (facilities.source_features, facilities.loaded, facilities.rejected) == (4, 2, 2)
    reasons = " | ".join(facilities.rejections)
    assert "SYN-F3" in reasons
    assert "outside the service area" in reasons
    assert "SYN-F4" in reasons
    assert "axes swapped" in reasons
    assert files["protected_areas.geojson"].repaired == 1


async def test_lineage_is_recorded_for_every_file(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT l.source_file, l.source_checksum_sha256, l.source_crs, l.status, l.loaded_count,
                           l.rejected_count, l.repaired_count, l.finished_at >= l.started_at AS finished,
                           l.loader_version, l.loaded_by, s.code AS source, s.licence, y.code AS layer,
                           r.code AS release
                    FROM meta.dataset_load l
                    JOIN meta.data_source s ON s.id = l.source_id
                    JOIN meta.layer y ON y.id = l.layer_id
                    JOIN meta.ref_data_release r ON r.id = l.release_id
                    """
                )
            )
        ).all()
    assert len(rows) == 7 + 10
    for row in rows:
        directory = SYNTHETIC_MANIFEST.parent if row.release == SYNTHETIC_RELEASE else OPEN_MANIFEST.parent
        content = (directory / row.source_file).read_bytes()
        assert row.source_checksum_sha256 == hashlib.sha256(content).hexdigest()
        assert row.loaded_count == len(json.loads(content)["features"]) - row.rejected_count
        assert (row.status, row.finished, row.source_crs) == ("completed", True, "EPSG:4326")
        assert row.loader_version.startswith("gis-core-service ")
        assert row.loaded_by == spatial_world.settings.db_migrator_user
    licences = {row.source: row.licence for row in rows}
    assert licences == {
        "geoboundaries-lka-osm": "ODbL-1.0",
        "geoboundaries-lka-ocha": "CC-BY-3.0-IGO",
        "natural-earth-10m": "public-domain",
        "gis-core-fixtures": "CC0-1.0",
    }


async def test_admin_hierarchy_is_linked(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.level, p.name AS parent, count(*) AS n
                    FROM ref.admin_area c LEFT JOIN ref.admin_area p ON p.id = c.parent_id
                    WHERE c.release_id = :release AND c.level >= 3
                    GROUP BY 1, 2 ORDER BY 1, 2
                    """
                ),
                {"release": spatial_world.open_data.release_id},
            )
        ).all()
        orphans = await session.scalar(
            text("SELECT count(*) FROM ref.admin_area WHERE level >= 2 AND parent_id IS NULL")
        )
        wrong_province = await session.scalar(
            text(
                """
                SELECT count(*) FROM ref.admin_area d JOIN ref.admin_area p ON p.id = d.parent_id
                WHERE d.level = 2 AND d.release_id = :release AND left(d.code, 4) <> p.code
                """
            ),
            {"release": spatial_world.open_data.release_id},
        )
    assert [tuple(r) for r in rows] == [
        (3, "Anuradhapura District", 22),
        (3, "Polonnaruwa District", 7),
        (4, "Palugaswewa", 16),
    ]
    assert orphans == 0
    assert wrong_province == 0


async def test_settlements_are_linked_to_the_deepest_admin_area(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        result = await session.execute(
            text(
                "SELECT s.name AS settlement, a.name AS area, "
                "public.ST_Covers(a.geom, s.label_point) AS covers "
                "FROM ref.settlement s JOIN ref.admin_area a ON a.id = s.admin_area_id"
            )
        )
        rows = {row.settlement: (row.area, row.covers) for row in result.all()}
    assert len(rows) == 14 + 2
    assert rows["Anuradhapura"] == ("Nuwaragam Palatha Central", True)  # DS divisions are loaded there
    assert rows["Kandy"] == ("Kandy District", True)  # only provinces and districts around Kandy
    assert rows["Fixture Village"] == ("Fixture North-West DS", True)
    # Fixture Town's representative point lies on the corner shared by several areas: any of them is right.
    assert rows["Fixture Town"][0] in {"Fixture GN East", "Fixture North-West DS", "Fixture East DS"}
    # Two coastal points of the 1:10m data fall just outside the generalised coastline (9 m and 67 m);
    # they are linked to the nearest area within 1 km instead.
    assert rows["Puttalan"] == ("Puttalam District", False)
    assert rows["Galle"] == ("Galle District", False)
    assert sum(not covers for _, covers in rows.values()) == 2


async def test_published_releases_cannot_be_loaded_into(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        loader = ReferenceDataLoader(session, spatial_world.service_area)
        with pytest.raises(ReferenceLoadError, match="published"):
            await loader.load(OPEN_MANIFEST)


async def test_the_same_file_cannot_be_loaded_twice_into_a_release(spatial_world: SpatialWorld) -> None:
    async def load_twice() -> None:
        async with transaction(spatial_world.migrator_sessions) as session:
            loader = ReferenceDataLoader(session, spatial_world.service_area)
            await loader.load(SYNTHETIC_MANIFEST, release_code="ref-2026.09-twice")
            await loader.load(SYNTHETIC_MANIFEST, release_code="ref-2026.09-twice")

    with pytest.raises(ReferenceLoadError, match="already loaded into this release"):
        await load_twice()


async def test_admin_areas_without_a_level_are_rejected(spatial_world: SpatialWorld, tmp_path: Path) -> None:
    manifest = json.loads(SYNTHETIC_MANIFEST.read_text(encoding="utf-8"))
    admin = json.loads((SYNTHETIC_MANIFEST.parent / "admin_level1.geojson").read_text(encoding="utf-8"))
    (tmp_path / "admin.geojson").write_text(json.dumps(admin), encoding="utf-8")
    manifest["files"] = [{**manifest["files"][0], "path": "admin.geojson", "properties": {}}]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    async with transaction(spatial_world.migrator_sessions) as session:
        result = await ReferenceDataLoader(session, spatial_world.service_area).load(
            tmp_path / "manifest.json", release_code="ref-2026.09-nolevel"
        )
        await session.rollback()
    (file_result,) = result.files
    assert (file_result.loaded, file_result.rejected) == (0, 1)
    assert "level" in file_result.rejections[0]


async def test_a_failed_file_leaves_nothing_behind(spatial_world: SpatialWorld, tmp_path: Path) -> None:
    manifest = json.loads(SYNTHETIC_MANIFEST.read_text(encoding="utf-8"))
    broken = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "BROKEN-1",
                "properties": {"name": "Broken zone", "risk_type": "volcano", "severity": 9},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[80.71, 8.01], [80.72, 8.01], [80.72, 8.02], [80.71, 8.01]]],
                },
            }
        ],
    }
    (tmp_path / "broken.geojson").write_text(json.dumps(broken), encoding="utf-8")
    manifest["files"] = [{**manifest["files"][5], "path": "broken.geojson"}]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DBAPIError, match=r"ck_risk_zone_(risk_type|severity)"):
        async with transaction(spatial_world.migrator_sessions) as session:
            await ReferenceDataLoader(session, spatial_world.service_area).load(
                tmp_path / "manifest.json", release_code="ref-2026.09-broken"
            )
    async with transaction(spatial_world.migrator_sessions) as session:
        left = await session.scalar(
            text("SELECT count(*) FROM meta.ref_data_release WHERE code = 'ref-2026.09-broken'")
        )
    assert left == 0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"release": {"code": "2026-09"}}, "release.code"),
        ({"files": [{"path": "x.geojson", "layer": "ref.notification_location"}]}, "files.0.layer"),
    ],
)
async def test_invalid_manifests_are_reported(
    spatial_world: SpatialWorld, tmp_path: Path, change: dict[str, object], message: str
) -> None:
    manifest = {**json.loads(SYNTHETIC_MANIFEST.read_text(encoding="utf-8")), **change}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    async with transaction(spatial_world.migrator_sessions) as session:
        with pytest.raises(ReferenceLoadError) as info:
            await ReferenceDataLoader(session, spatial_world.service_area).load(tmp_path / "manifest.json")
    locations = [error["location"] for error in info.value.extensions["errors"]]
    assert any(location.startswith(message) for location in locations), locations


async def test_downgrade_refuses_to_discard_reference_data(spatial_world: SpatialWorld) -> None:
    with pytest.raises(DBAPIError, match="downgrade refused"):
        await run_alembic(spatial_world.settings, "downgrade", "20260915_0002")
