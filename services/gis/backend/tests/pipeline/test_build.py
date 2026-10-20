"""A release built end to end from a small source in SLD99 (EPSG:5235), with GDAL doing the work."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import geopandas as gpd
import pyogrio
import pyproj
import pytest
from shapely.geometry import Point

from app.pipeline.build import build
from app.pipeline.crs import ControlPoint, CoordinateOperation, choose_operation, verify_operation
from app.pipeline.errors import CrsError, FileQaError, LicenceError
from app.schemas.reference_data import FileQaReport, Manifest

# Real places near Habarana (WGS 84), stored by the "agency" in SLD99.
PLACES = {
    "V-1": ("Habarana", "town", (80.75646, 8.04232)),
    "V-2": ("Palugaswewa", "village", (80.70909, 8.06359)),
    "V-3": ("Hiriwadunna", "village", (80.7434, 8.0167)),
}
TO_SLD99 = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:5235", always_xy=True)

PROFILE = """
[profile]
name = "pipetest"
purpose = "test"
release = "ref-{{year}}.{{month}}-pipetest"
description = "Pipeline test"

[areas]
national = [79.44, 5.66, 82.15, 10.08]
pilot = [80.45, 7.75, 81.10, 8.30]

[sources.agency-villages]
name = "Villages (test delivery)"
publisher = "Test agency"
licence = "{licence}"
attribution = "Test agency (CC BY 4.0)"
commercial_use_allowed = true
redistribution_allowed = true
file = "agency/villages.gpkg"
version = "delivery 1"
source_crs = "EPSG:5235"
geometry_source = "survey"

[[sources.agency-villages.control_points]]
name = "Habarana"
source = [{cp_x}, {cp_y}]
wgs84 = [80.75646, 8.04232]
tolerance_m = 0.05

[[datasets]]
name = "villages"
layer = "ref.settlement"
source = "agency-villages"
adapter = "vector"
area = "pilot"
id_field = "vid"
id_prefix = "agency-"
fields = {{ name = "vname", settlement_type = "kind" }}
values = {{ settlement_type = {{ "Town" = "town", "Village" = "village" }} }}
accuracy_m = 20
qa = {{ expected_area = "pilot", min_features = {min_features} }}
"""


def write_source(raw: Path, *, with_unidentified: bool = False) -> None:
    rows: list[tuple[str | None, str, str, tuple[float, float]]] = [
        (vid, name, kind.title(), TO_SLD99.transform(*lonlat)) for vid, (name, kind, lonlat) in PLACES.items()
    ]
    if with_unidentified:
        rows.append((None, "No id", "Village", TO_SLD99.transform(80.72, 8.05)))
    frame = gpd.GeoDataFrame(
        {
            "vid": [row[0] for row in rows],
            "vname": [row[1] for row in rows],
            "kind": [row[2] for row in rows],
        },
        geometry=[Point(row[3]) for row in rows],
        crs="EPSG:5235",
    )
    (raw / "agency").mkdir(parents=True, exist_ok=True)
    pyogrio.write_dataframe(frame, raw / "agency" / "villages.gpkg", layer="villages")


def write_profile(path: Path, *, licence: str = "CC-BY-4.0", min_features: int = 3) -> Path:
    cp_x, cp_y = TO_SLD99.transform(80.75646, 8.04232)
    path.write_text(
        PROFILE.format(licence=licence, cp_x=cp_x, cp_y=cp_y, min_features=min_features), encoding="utf-8"
    )
    return path


def test_a_release_is_built_with_its_lineage_and_is_reproducible(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    write_source(raw)
    profile = write_profile(tmp_path / "profile.toml")
    result = build(
        profile, raw_dir=raw, output_root=out, release_code="ref-2026.09-pipetest", allow_download=False
    )

    manifest = Manifest.read(result.manifest)
    (spec,) = manifest.files
    assert (spec.layer, spec.source, spec.source_crs) == ("ref.settlement", "agency-villages", "EPSG:5235")
    assert spec.coordinate_operation is not None
    assert "accuracy 14 m" in spec.coordinate_operation
    assert spec.source_version == "delivery 1"
    assert spec.original_file == "villages.gpkg"
    assert spec.geometry_accuracy_m == 20
    assert spec.geometry_source == "survey"
    assert spec.tool_versions["gdal"]

    features = json.loads(gzip.decompress((result.directory / spec.path).read_bytes()))["features"]
    by_id = {feature["id"]: feature for feature in features}
    assert set(by_id) == {f"agency-{key}" for key in PLACES}
    for key, (name, kind, (lon, lat)) in PLACES.items():
        feature = by_id[f"agency-{key}"]
        assert feature["properties"]["name"] == name
        assert feature["properties"]["settlement_type"] == kind
        x, y = feature["geometry"]["coordinates"]
        # Back where they came from, to about a centimetre (the transformation is exact both ways).
        assert x == pytest.approx(lon, abs=2e-7)
        assert y == pytest.approx(lat, abs=2e-7)

    report = FileQaReport.model_validate_json((result.directory / str(spec.qa_report)).read_text())
    assert report.status == "passed"
    operation = next(item for item in report.findings if item.check == "crs.operation")
    assert operation.details["controlPoints"] == 1
    sources_md = (result.directory / "SOURCES.md").read_text(encoding="utf-8")
    assert "Test agency (CC BY 4.0)" in sources_md
    record = json.loads((result.directory / "build.json").read_text(encoding="utf-8"))
    assert record["sources"]["agency-villages"]["sha256"] == spec.original_checksum_sha256

    checksum = report.sha256
    again = build(
        profile,
        raw_dir=raw,
        output_root=out,
        release_code="ref-2026.09-pipetest",
        allow_download=False,
        force=True,
    )
    assert again.datasets[0].sha256 == checksum


def test_features_without_identifiers_fail_the_file_qa(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    write_source(raw, with_unidentified=True)
    profile = write_profile(tmp_path / "profile.toml")
    with pytest.raises(FileQaError, match="villages"):
        build(
            profile, raw_dir=raw, output_root=out, release_code="ref-2026.09-pipetest", allow_download=False
        )
    report = FileQaReport.model_validate_json(
        (out / "ref-2026.09-pipetest" / "qa" / "villages.qa.json").read_text()
    )
    checks = {(item.check, item.severity) for item in report.findings}
    assert ("identifier.missing", "warning") in checks
    assert ("outlier.rejected", "error") in checks  # 1 of 4 left out, above the 1 % allowed


def test_a_restricted_licence_stops_the_build_before_anything_is_written(tmp_path: Path) -> None:
    raw, out = tmp_path / "raw", tmp_path / "out"
    write_source(raw)
    profile = write_profile(tmp_path / "profile.toml", licence="CC-BY-NC-4.0")
    with pytest.raises(LicenceError, match="restricts commercial use"):
        build(profile, raw_dir=raw, output_root=out, allow_download=False)
    assert not out.exists()


def test_ogr2ogr_and_pyproj_must_agree_on_the_operation() -> None:
    sld99 = choose_operation("EPSG:5235")
    habarana = TO_SLD99.transform(80.75646, 8.04232)
    verified = verify_operation(
        sld99, [habarana], control_points=[ControlPoint("Habarana", habarana, (80.75646, 8.04232), 0.05)]
    )
    assert verified["maxDeviationDeg"] < 1e-7
    # A control point surveyed 100 m away from where the operation puts it.
    with pytest.raises(CrsError, match="lands"):
        verify_operation(
            sld99, [], control_points=[ControlPoint("Off", habarana, (80.75646, 8.04322), 1.0)], label="x"
        )
    # The pipeline in the wrong axis order (what always_xy=True produces) is caught, not applied.
    group = pyproj.transformer.TransformerGroup("EPSG:5235", "EPSG:4326", always_xy=True)
    swapped = CoordinateOperation(
        "EPSG:5235", "swapped", group.transformers[0].definition, 14.0, sld99.proj_version
    )
    with pytest.raises(CrsError, match="disagree"):
        verify_operation(swapped, [habarana], label="x")
