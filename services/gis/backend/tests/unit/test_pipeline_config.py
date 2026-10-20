"""Reference data pipeline rules that need neither GDAL nor GeoPandas: profiles, licences, CRS choice,
source provenance, attribution and the development seed's input."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Environment, Settings
from app.pipeline.acquire import acquire, read_osm_pbf_header
from app.pipeline.crs import choose_operation, resolve_source_crs
from app.pipeline.errors import CrsError, LicenceError, ProfileError, SourceError
from app.pipeline.profile import Profile, SourceConfig, check_licences, load_profile, raw_path
from app.schemas.reference_data import Manifest, ReferenceDataError, merge_attribution
from app.tools.seed_dev_data import (
    SeedRefusedError,
    device_id,
    read_sample,
    refuse_production,
)

REPOSITORY = Path(__file__).resolve().parents[3]
PROFILES = REPOSITORY / "data" / "pipeline" / "profiles"
SAMPLE = REPOSITORY / "data" / "sample"

OPEN_SOURCE: dict[str, Any] = {
    "name": "An open source",
    "publisher": "Somebody",
    "licence": "CC-BY-4.0",
    "attribution": "Somebody (CC BY 4.0)",
    "commercial_use_allowed": True,
    "redistribution_allowed": True,
    "file": "open.geojson",
    "version": "1",
}


def profile(
    *, purpose: str = "development", source: dict[str, Any] | None = None, adapter: str = "vector"
) -> Profile:
    values = {**OPEN_SOURCE, **(source or {})}
    dataset: dict[str, Any] = {
        "name": "roads",
        "layer": "ref.road",
        "source": "src",
        "adapter": adapter,
        "accuracy_m": 10,
    }
    if adapter == "vector":
        dataset["id_field"] = "id"
    return Profile.model_validate(
        {
            "profile": {
                "name": "t",
                "purpose": purpose,
                "release": "ref-{year}.{month}-t",
                "description": "t",
            },
            "areas": {"national": [79.44, 5.66, 82.15, 10.08]},
            "sources": {"src": {"code": "src", **values}},
            "datasets": [dataset],
        }
    )


# --- profiles and licences ----------------------------------------------------------------------------------


def test_the_development_profile_uses_open_licences_only() -> None:
    dev = load_profile(PROFILES / "dev.toml")
    notes = check_licences(dev)
    assert dev.profile.purpose == "development"
    assert all("share-alike" in note for note in notes)
    licences = {dev.sources[dataset.source].licence for dataset in dev.datasets}
    assert licences <= {"ODbL-1.0", "CC-BY-3.0-IGO", "CC0-1.0"}
    assert not any("WDPA" in source.licence.upper() for source in dev.sources.values())


def test_the_production_example_refuses_to_build_until_every_licence_is_reviewed() -> None:
    production = load_profile(PROFILES / "production.example.toml")
    with pytest.raises(LicenceError) as info:
        check_licences(production)
    problems = info.value.extensions["problems"]
    used = {dataset.source for dataset in production.datasets}
    for code in used:
        assert any(
            problem.startswith(f"{code}: a production profile needs an approved") for problem in problems
        )
    # Nothing is assumed about agency licences: they do not permit commercial use until someone says so.
    assert any("does not permit commercial use" in problem for problem in problems)


def test_a_wdpa_source_needs_written_permission_even_for_development() -> None:
    wdpa = {"licence": "WDPA-terms", "attribution": "UNEP-WCMC and IUCN, Protected Planet"}
    with pytest.raises(LicenceError, match="restricts commercial use"):
        check_licences(profile(source=wdpa))
    permitted = profile(source={**wdpa, "permission_reference": "UNEP-WCMC letter 2026-123"})
    assert check_licences(permitted) == []


def test_a_non_commercial_licence_is_refused_without_permission() -> None:
    with pytest.raises(LicenceError, match="does not permit commercial use"):
        check_licences(profile(source={"licence": "CC-BY-NC-4.0", "commercial_use_allowed": False}))


def test_a_rejected_review_is_refused() -> None:
    rejected = {
        "review": {
            "status": "rejected",
            "reviewed_by": "Legal",
            "reviewed_on": "2026-09-01",
            "reference": "LEGAL-42",
        }
    }
    with pytest.raises(LicenceError, match="review was rejected"):
        check_licences(profile(source=rejected))


def test_a_production_profile_needs_approved_reviews_and_no_placeholders() -> None:
    with pytest.raises(LicenceError, match="needs an approved licence review"):
        check_licences(profile(purpose="production"))
    approved = {
        "review": {
            "status": "approved",
            "reviewed_by": "Data governance",
            "reviewed_on": "2026-09-01",
            "reference": "DG-7",
        }
    }
    assert check_licences(profile(purpose="production", source=approved)) == []
    with pytest.raises(LicenceError, match="placeholder or synthetic data"):
        check_licences(profile(purpose="production", source=approved, adapter="placeholder"))


def test_obligations_are_reported() -> None:
    notes = check_licences(profile(source={"share_alike": True, "redistribution_allowed": False}))
    assert any("share-alike" in note for note in notes)
    assert any("exports of its layers are refused" in note for note in notes)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"download": "http://example.org/data.zip"}, "downloads must use https"),
        ({"version": None}, "state its version"),
        ({"geometry_source": "guessed"}, "must be one of"),
    ],
)
def test_sources_must_say_where_they_come_from(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SourceConfig.model_validate({"code": "src", **OPEN_SOURCE, **change})


def test_a_profile_with_unknown_references_is_refused(tmp_path: Path) -> None:
    text = (
        (PROFILES / "dev.toml")
        .read_text(encoding="utf-8")
        .replace('source = "osm-geofabrik-lka"\nadapter = "osm"', 'source = "nowhere"\nadapter = "osm"', 1)
    )
    (tmp_path / "broken.toml").write_text(text, encoding="utf-8")
    with pytest.raises(ProfileError) as info:
        load_profile(tmp_path / "broken.toml")
    assert "unknown source nowhere" in json.dumps(info.value.extensions)


def test_release_codes_follow_the_pattern() -> None:
    dev = load_profile(PROFILES / "dev.toml")
    assert dev.profile.release_code().endswith("-dev")
    assert dev.profile.release_code().startswith("ref-")


def test_source_files_are_found_relative_to_the_raw_directory_or_the_profile(tmp_path: Path) -> None:
    raw = SourceConfig.model_validate({"code": "src-a", **OPEN_SOURCE})
    beside = SourceConfig.model_validate(
        {"code": "src-b", **OPEN_SOURCE, "file": "../x.geojson", "base": "profile"}
    )
    assert raw_path(tmp_path, raw) == tmp_path / "open.geojson"
    assert raw_path(tmp_path, beside, tmp_path / "profiles") == (tmp_path / "x.geojson").resolve()
    with pytest.raises(ProfileError):
        raw_path(tmp_path, beside)


# --- coordinate reference systems ---------------------------------------------------------------------------


def test_the_pipeline_never_guesses_a_crs() -> None:
    with pytest.raises(CrsError, match="does not guess"):
        resolve_source_crs(None, None, label="x")


def test_a_declared_crs_must_match_the_file() -> None:
    import pyproj

    sld99 = pyproj.CRS("EPSG:5235").to_wkt()
    assert resolve_source_crs(None, sld99, label="x") == "EPSG:5235"
    assert resolve_source_crs("EPSG:5235", sld99, label="x") == "EPSG:5235"
    with pytest.raises(CrsError, match="declares EPSG:5234"):
        resolve_source_crs("EPSG:5234", sld99, label="x")


def test_the_operation_to_wgs84_records_its_accuracy() -> None:
    sld99 = choose_operation("EPSG:5235")
    assert not sld99.is_identity
    assert sld99.accuracy_m == pytest.approx(14)
    assert "accuracy 14 m" in sld99.lineage()
    assert "+proj=pipeline" in sld99.lineage()
    kandawala = choose_operation("EPSG:5234")
    assert kandawala.accuracy_m == pytest.approx(35)
    wgs84 = choose_operation("EPSG:4326")
    assert wgs84.is_identity
    assert wgs84.lineage().startswith("none")


def test_a_pinned_operation_must_exist() -> None:
    with pytest.raises(CrsError, match="matches"):
        choose_operation("EPSG:5235", pinned="no such operation", label="x")


# --- source provenance --------------------------------------------------------------------------------------


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _field(number: int, value: int | bytes) -> bytes:
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    return _varint(number << 3 | 2) + _varint(len(value)) + value


def osm_pbf(path: Path, *, compressed: bool) -> Path:
    header = (
        _field(4, b"OsmSchema-V0.6")
        + _field(4, b"DenseNodes")
        + _field(16, b"osmium/1.16.0")
        + _field(32, 1_790_000_000)
        + _field(33, 4321)
    )
    blob = _field(3, zlib.compress(header)) if compressed else _field(1, header)
    blob_header = _field(1, b"OSMHeader") + _field(3, len(blob))
    path.write_bytes(struct.pack(">I", len(blob_header)) + blob_header + blob)
    return path


@pytest.mark.parametrize("compressed", [True, False])
def test_the_osm_replication_timestamp_is_read_from_the_pbf_header(tmp_path: Path, compressed: bool) -> None:
    header = read_osm_pbf_header(osm_pbf(tmp_path / "x.osm.pbf", compressed=compressed))
    assert header["osmosis_replication_timestamp"] == 1_790_000_000
    assert header["osmosis_replication_sequence_number"] == 4321
    assert header["writingprogram"] == "osmium/1.16.0"
    assert header["required_features"] == ["OsmSchema-V0.6", "DenseNodes"]


def test_a_file_that_is_not_osm_pbf_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.osm.pbf").write_bytes(b"\x00\x00\x00\x05hello")
    with pytest.raises(SourceError):
        read_osm_pbf_header(tmp_path / "x.osm.pbf")


def test_acquiring_a_file_records_and_then_enforces_its_provenance(tmp_path: Path) -> None:
    osm_pbf(tmp_path / "osm.pbf", compressed=True)
    source = SourceConfig.model_validate(
        {
            "code": "osm",
            **{**OPEN_SOURCE, "version": None},
            "file": "osm.pbf",
            "version_from": "osm_replication_timestamp",
        }
    )
    first = acquire(source, tmp_path, allow_download=False)
    assert first.version.startswith("OpenStreetMap data as of 2026-09-21T")
    assert "replication sequence 4321" in first.version
    assert "placed in the raw directory by hand" in first.retrieved_basis
    record = json.loads((tmp_path / "osm.pbf.provenance.json").read_text(encoding="utf-8"))
    assert record["sha256"] == first.sha256
    # The file changes under the pipeline: noticed, not silently used.
    osm_pbf(tmp_path / "osm.pbf", compressed=False)
    with pytest.raises(SourceError, match="changed since it was retrieved"):
        acquire(source, tmp_path, allow_download=False)


def test_a_missing_file_is_not_downloaded_when_downloads_are_off(tmp_path: Path) -> None:
    source = SourceConfig.model_validate(
        {"code": "src-x", **OPEN_SOURCE, "download": "https://example.org/open.geojson"}
    )
    with pytest.raises(SourceError, match="allow downloads"):
        acquire(source, tmp_path, allow_download=False)


def test_an_expected_checksum_is_enforced(tmp_path: Path) -> None:
    (tmp_path / "open.geojson").write_text("{}", encoding="utf-8")
    source = SourceConfig.model_validate({"code": "src-x", **OPEN_SOURCE, "sha256": "0" * 64})
    with pytest.raises(SourceError, match="the profile expects"):
        acquire(source, tmp_path, allow_download=False)


# --- the sample and its attribution -------------------------------------------------------------------------


def test_the_committed_sample_release_is_a_valid_development_manifest() -> None:
    manifest = Manifest.read(SAMPLE / "ref-2026.09-dev" / "manifest.json")
    assert manifest.release.purpose == "development"
    layers = {spec.layer for spec in manifest.files}
    assert layers == {
        "ref.admin_area",
        "ref.settlement",
        "ref.facility",
        "ref.road",
        "ref.water_body",
        "ref.protected_area",
        "ref.risk_zone",
    }
    for spec in manifest.files:
        assert (SAMPLE / "ref-2026.09-dev" / spec.path).is_file()
        assert spec.qa_report is not None
        assert (SAMPLE / "ref-2026.09-dev" / spec.qa_report).is_file()
        assert spec.original_checksum_sha256 is not None
        assert spec.source_version
        assert spec.geometry_accuracy_m > 0
    assert not any("WDPA" in source.licence.upper() for source in manifest.sources)


def test_a_manifest_refuses_a_non_commercial_source_without_permission() -> None:
    document = json.loads((SAMPLE / "ref-2026.09-dev" / "manifest.json").read_text(encoding="utf-8"))
    document["sources"][0]["commercialUseAllowed"] = False
    with pytest.raises(ValueError, match="does not permit commercial use"):
        Manifest.model_validate(document)
    with pytest.raises(ReferenceDataError, match="cannot read manifest"):
        Manifest.read(Path("/nonexistent/manifest.json"))


def test_attribution_statements_are_merged_without_repeats() -> None:
    merged = merge_attribution(
        [
            "© OpenStreetMap contributors",
            "© OpenStreetMap contributors (ODbL); geoBoundaries",
            "OCHA ROAP",
            "OCHA ROAP",
            "  ",
        ]
    )
    assert merged == ["© OpenStreetMap contributors (ODbL); geoBoundaries", "OCHA ROAP"]


def test_the_seed_sample_is_valid_and_labelled() -> None:
    sample = read_sample(SAMPLE / "operational" / "wildlife-dept.json")
    assert sample.tenant.tenant_id == "wildlife-dept"
    labelled = [
        *((item.name, item.attributes) for item in sample.sites),
        *((item.name, item.attributes) for item in sample.devices),
        *((item.name, item.attributes) for item in sample.geofences),
    ]
    for name, attributes in labelled:
        assert name.startswith("DEV ")
        assert attributes.get("sample") is True
    assert all(event.metadata.get("sample") is True for event in sample.events)


def test_the_seed_refuses_a_sample_that_refers_to_unknown_devices(tmp_path: Path) -> None:
    document = json.loads((SAMPLE / "operational" / "wildlife-dept.json").read_text(encoding="utf-8"))
    document["events"][0]["device"] = "no-such-device"
    (tmp_path / "sample.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SeedRefusedError, match="no-such-device"):
        read_sample(tmp_path / "sample.json")


def test_the_seed_refuses_production() -> None:
    settings = Settings.model_construct(env=Environment.PRODUCTION)
    with pytest.raises(SeedRefusedError, match="production"):
        refuse_production(settings)
    refuse_production(Settings.model_construct(env=Environment.DEVELOPMENT))


def test_seeded_device_identifiers_are_stable_per_tenant() -> None:
    assert device_id("wildlife-dept", "hb-cam-01") == device_id("wildlife-dept", "hb-cam-01")
    assert device_id("wildlife-dept", "hb-cam-01") != device_id("other-tenant", "hb-cam-01")
