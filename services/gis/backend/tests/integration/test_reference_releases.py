"""Reference data releases: database QA, the publish gate, waivers, licences and lineage.

Each test loads a small draft release from the synthetic fixture world inside one transaction and rolls
it back, so the module's world is left as it was.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Environment
from app.db.session import transaction
from app.services.reference_loader import ReferenceDataLoader
from app.services.reference_qa import CHECKS, ReleaseQaError
from app.services.reference_releases import ReleaseManager, ReleaseStateError
from tests.integration.conftest import SpatialWorld
from tests.integration.spatial_world import OPEN_RELEASE, SYNTHETIC_MANIFEST, SYNTHETIC_RELEASE

ROADS = "roads.geojson"
PROTECTED = "protected_areas.geojson"
FACILITIES = "facilities.geojson"


def draft_manifest(
    directory: Path,
    files: Sequence[str],
    *,
    purpose: str | None = None,
    source: dict[str, Any] | None = None,
    qa: dict[str, Any] | None = None,
) -> Path:
    """A manifest of some synthetic fixture files, with the release, source or QA expectations changed."""
    manifest = json.loads(SYNTHETIC_MANIFEST.read_text(encoding="utf-8"))
    chosen = [item for item in manifest["files"] if item["path"] in files]
    for item in chosen:
        shutil.copyfile(SYNTHETIC_MANIFEST.parent / item["path"], directory / item["path"])
        if qa is not None:
            item["qa"] = {**item.get("qa", {}), **qa}
        if source is not None:
            item["source"] = source["code"]
    manifest["files"] = chosen
    if purpose is not None:
        manifest["release"]["purpose"] = purpose
    if source is not None:
        manifest["sources"] = [source]
    path = directory / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@asynccontextmanager
async def rolled_back(world: SpatialWorld) -> AsyncIterator[AsyncSession]:
    async with transaction(world.migrator_sessions) as session:
        yield session
        await session.rollback()


async def load(session: AsyncSession, world: SpatialWorld, manifest: Path, code: str) -> ReleaseManager:
    await ReferenceDataLoader(session, world.service_area).load(manifest, release_code=code)
    return ReleaseManager(session)


async def findings(session: AsyncSession, code: str) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            """
            SELECT f.id, f.check_code, f.severity, f.waivable, f.source_feature_id, f.waived_at
            FROM meta.qa_finding f JOIN meta.ref_data_release r ON r.id = f.release_id
            WHERE r.code = :code ORDER BY f.id
            """
        ),
        {"code": code},
    )
    return [dict(row) for row in rows.mappings()]


async def test_every_check_is_documented_once() -> None:
    codes = [check.code for check in CHECKS]
    assert len(codes) == len(set(codes))
    # The checks the pipeline promises: CRS, validity, duplicates, identifiers, outliers, extents, topology.
    families = {code.split(".")[0] for code in codes}
    assert {"crs", "geometry", "duplicate", "identifier", "outlier", "topology", "licence"} <= families


async def test_qa_records_its_findings_with_the_content_it_checked(
    spatial_world: SpatialWorld, tmp_path: Path
) -> None:
    manifest = draft_manifest(tmp_path, [PROTECTED, FACILITIES])
    async with rolled_back(spatial_world) as session:
        manager = await load(session, spatial_world, manifest, "ref-2026.09-qa")
        summary = await manager.run_qa("ref-2026.09-qa")
        stored = await findings(session, "ref-2026.09-qa")
        run = (
            await session.execute(
                text(
                    "SELECT q.status, "
                    "q.content_fingerprint = meta.release_fingerprint(q.release_id) AS fresh "
                    "FROM meta.qa_run q WHERE q.id = :id"
                ),
                {"id": summary.run_id},
            )
        ).one()
    assert (run.status, run.fresh) == (summary.status, True)
    checks = {(item["check_code"], item["severity"]) for item in stored}
    # SYN-PA2 is a self-intersecting polygon the loader repaired; two facilities were rejected.
    assert ("geometry.repaired", "warning") in checks
    assert ("outlier.rejected", "info") in checks
    # A test release: synthetic content and an unreviewed licence are noted, not errors.
    assert ("content.synthetic", "info") in checks
    assert ("licence.unreviewed", "info") in checks
    repaired = next(item for item in stored if item["check_code"] == "geometry.repaired")
    assert repaired["source_feature_id"] == "SYN-PA2"
    assert summary.status == "warnings"


async def test_a_release_is_published_only_after_a_fresh_qa_run(
    spatial_world: SpatialWorld, tmp_path: Path
) -> None:
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    first = draft_manifest(tmp_path / "first", [ROADS])
    second = draft_manifest(tmp_path / "second", [PROTECTED])
    code = "ref-2026.09-gate"
    async with rolled_back(spatial_world) as session:
        manager = await load(session, spatial_world, first, code)
        with pytest.raises(ReleaseQaError, match="has not been checked"):
            await manager.publish(code)
        await manager.run_qa(code)
        # More data after the check: the check no longer describes the release.
        await load(session, spatial_world, second, code)
        with pytest.raises(ReleaseQaError, match="changed after its last QA run"):
            await manager.publish(code)
        await manager.run_qa(code)
        record = await manager.publish(code)
        assert record.status == "published"
        with pytest.raises(ReleaseQaError, match="only drafts are checked"):
            await manager.run_qa(code)


async def test_an_error_blocks_publishing_until_it_is_waived_with_a_reason(
    spatial_world: SpatialWorld, tmp_path: Path
) -> None:
    manifest = draft_manifest(tmp_path, [ROADS], qa={"minFeatures": 50})
    code = "ref-2026.09-waiver"
    async with rolled_back(spatial_world) as session:
        manager = await load(session, spatial_world, manifest, code)
        summary = await manager.run_qa(code)
        assert summary.status == "failed"
        (error,) = [item for item in await findings(session, code) if item["severity"] == "error"]
        assert (error["check_code"], error["waivable"]) == ("outlier.count", True)
        with pytest.raises(ReleaseQaError, match="1 unresolved QA errors"):
            await manager.publish(code)
        with pytest.raises(ReleaseStateError, match="needs a reason"):
            await manager.waive(code, error["id"], "   ")
        await manager.waive(code, error["id"], "pilot extract; the national roads follow in the next release")
        audit = (
            await session.execute(
                text(
                    "SELECT operation, parameters FROM audit.entry WHERE object_id = :id "
                    "AND operation = 'reference_release.qa_waiver'"
                ),
                {"id": str(error["id"])},
            )
        ).one()
        assert audit.parameters["check"] == "outlier.count"
        assert audit.parameters["code"] == code
        assert audit.parameters["reason"].startswith("pilot extract")
        record = await manager.publish(code)
    assert record.status == "published"


async def test_a_restricted_licence_is_an_error_no_one_can_waive(
    spatial_world: SpatialWorld, tmp_path: Path
) -> None:
    # Declared as if commercial use were allowed (a manifest refuses a source that says it is not, unless a
    # written permission is recorded): the licence itself gives it away.
    wdpa_like = {
        "code": "wdpa-test",
        "name": "Protected areas under WDPA terms",
        "publisher": "UNEP-WCMC and IUCN",
        "licence": "WDPA-terms-of-use",
        "attribution": "UNEP-WCMC and IUCN, Protected Planet",
        "commercialUseAllowed": True,
        "redistributionAllowed": False,
    }
    manifest = draft_manifest(tmp_path, [PROTECTED], source=wdpa_like)
    code = "ref-2026.09-wdpa"
    async with rolled_back(spatial_world) as session:
        manager = await load(session, spatial_world, manifest, code)
        assert (await manager.run_qa(code)).status == "failed"
        stored = await findings(session, code)
        restricted = [item for item in stored if item["check_code"] == "licence.restricted"]
        assert restricted
        assert all(item["severity"] == "error" and not item["waivable"] for item in restricted)
        with pytest.raises(ReleaseStateError, match="cannot be waived"):
            await manager.waive(code, restricted[0]["id"], "we would like to use it anyway")
        with pytest.raises(ReleaseQaError, match="unresolved QA errors"):
            await manager.publish(code)
        checks = {item["check_code"] for item in stored}
    # Informational: exports of this data will be refused.
    assert "licence.no_redistribution" in checks


async def test_a_production_release_needs_approved_licences_and_real_data(
    spatial_world: SpatialWorld, tmp_path: Path
) -> None:
    manifest = draft_manifest(tmp_path, [ROADS], purpose="production")
    code = "ref-2026.09-prod"
    async with rolled_back(spatial_world) as session:
        manager = await load(session, spatial_world, manifest, code)
        assert (await manager.run_qa(code)).status == "failed"
        errors = {item["check_code"] for item in await findings(session, code) if item["severity"] == "error"}
        with pytest.raises(ReleaseQaError):
            await manager.publish(code)
    # The fixture licence was never reviewed for this deployment, and the features are synthetic.
    assert {"licence.unreviewed", "content.synthetic"} <= errors


async def test_a_production_environment_serves_only_production_releases(
    spatial_world: SpatialWorld,
) -> None:
    async with rolled_back(spatial_world) as session:
        manager = ReleaseManager(session)
        with pytest.raises(ReleaseStateError, match="only serves production releases"):
            await manager.make_current(SYNTHETIC_RELEASE, environment=Environment.PRODUCTION)
        # Elsewhere the same release can be made current.
        record = await manager.make_current(SYNTHETIC_RELEASE, environment=Environment.DEVELOPMENT)
        assert record.is_current


async def test_every_dataset_records_its_lineage(spatial_world: SpatialWorld) -> None:
    async with transaction(spatial_world.migrator_sessions) as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT release_code, source_code, licence, source_reference, source_version,
                               imported_at, geometry_types, source_crs, storage_crs, geometry_accuracy_m,
                               attribution, redistribution_allowed
                        FROM meta.dataset_lineage WHERE release_code IN (:open, :synthetic)
                        """
                    ),
                    {"open": OPEN_RELEASE, "synthetic": SYNTHETIC_RELEASE},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 17
    for row in rows:
        missing = [name for name, value in row.items() if value is None or value == [] or value == ""]
        assert not missing, (row["source_code"], missing)
        assert row["storage_crs"] == "EPSG:4326"
        assert row["geometry_accuracy_m"] > 0
