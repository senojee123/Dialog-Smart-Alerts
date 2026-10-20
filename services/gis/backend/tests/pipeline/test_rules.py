"""OpenStreetMap tag rules, file QA and deterministic output."""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon

from app.pipeline import file_qa, writer
from app.pipeline.adapters import Extracted, Note
from app.pipeline.adapters.osm import facility_type, protected_area, road_class, settlement_type, water_type
from app.pipeline.crs import choose_operation
from app.schemas.reference_data import QaExpectations

SERVICE_AREA = (79.44, 5.66, 82.15, 10.08)

# --- OpenStreetMap tag rules --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"place": "town"}, "town"),
        ({"place": "city", "capital": "yes"}, "capital"),
        ({"place": "hamlet"}, "hamlet"),
        ({"place": "locality"}, None),
        ({"place": "suburb"}, None),
    ],
)
def test_settlement_types(tags: dict[str, Any], expected: str | None) -> None:
    assert settlement_type(tags) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"amenity": "police"}, "police_station"),
        ({"healthcare": "hospital"}, "hospital"),
        ({"amenity": "ranger_station", "operator": "Forest Department"}, "forest_office"),
        ({"amenity": "ranger_station"}, "wildlife_office"),
        (
            {"office": "government", "name": "Department of Wildlife Conservation, Habarana"},
            "wildlife_office",
        ),
        ({"office": "government", "name": "Divisional Secretariat"}, "government_office"),
        ({"shop": "bakery"}, None),
    ],
)
def test_facility_types(tags: dict[str, Any], expected: str | None) -> None:
    assert facility_type(tags) == expected


@pytest.mark.parametrize(
    ("highway", "ref", "expected"),
    [
        ("trunk", "A6", ("A", "ref")),
        ("primary", "A 11;B 502", ("A", "ref")),
        ("secondary", "b-293", ("B", "ref")),
        ("motorway", None, ("E", "highway")),
        ("residential", None, ("local", "highway")),
        ("track", None, ("track", "highway")),
        ("tertiary", None, ("unknown", "highway")),
    ],
)
def test_road_classes_come_from_the_route_number_first(
    highway: str, ref: str | None, expected: tuple[str, str]
) -> None:
    assert road_class(highway, ref) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"natural": "water", "name": "Hiriwadunna Wewa"}, "tank"),
        ({"natural": "water", "name": "Giant's Tank", "water": "reservoir"}, "tank"),
        ({"natural": "water", "name_en": "Periya Kulam"}, "tank"),
        ({"landuse": "reservoir", "name": "Victoria Reservoir"}, "reservoir"),
        ({"natural": "water", "water": "lagoon"}, "lagoon"),
        ({"natural": "wetland"}, "wetland"),
        ({"natural": "water"}, "other"),
    ],
)
def test_water_types_recognise_irrigation_tanks_by_name(tags: dict[str, Any], expected: str) -> None:
    assert water_type(tags)[0] == expected


def test_protected_areas_need_a_recognised_designation() -> None:
    park = protected_area({"name": "Minneriya National Park", "boundary": "national_park"})
    assert isinstance(park, dict)
    assert (park["designation"], park["managing_authority"]) == ("National Park", "DWC")
    forest = protected_area(
        {"name": "Hurulu Forest Reserve", "boundary": "protected_area", "operator": "Forest Department"}
    )
    assert isinstance(forest, dict)
    assert forest["managing_authority"] == "FD"
    assert forest["osm_managing_authority_basis"] == "operator tag"
    assert protected_area({"boundary": "protected_area"}) == "no name"
    assert isinstance(protected_area({"name": "Some Estate", "boundary": "protected_area"}), str)


# --- file QA ------------------------------------------------------------------------------------------------


def extracted(
    rows: list[tuple[str | None, dict[str, Any], Any]], notes: list[Note] | None = None
) -> Extracted:
    frame = gpd.GeoDataFrame(
        {"id": [row[0] for row in rows], "properties": [row[1] for row in rows]},
        geometry=[row[2] for row in rows],
        crs=4326,
    )
    return Extracted(
        frame=frame,
        operation=choose_operation("EPSG:4326"),
        transformation="test",
        source_crs="EPSG:4326",
        read_count=len(rows),
        notes=notes or [],
    )


BOWTIE = Polygon([(80.70, 8.00), (80.72, 8.02), (80.72, 8.00), (80.70, 8.02), (80.70, 8.00)])
SQUARE = Polygon([(80.75, 8.03), (80.76, 8.03), (80.76, 8.04), (80.75, 8.04), (80.75, 8.03)])


def test_file_qa_leaves_out_what_cannot_be_loaded_and_says_why() -> None:
    result = file_qa.check(
        extracted(
            [
                ("pa-1", {"name": "A park"}, SQUARE),
                ("pa-2", {"name": "Bowtie"}, BOWTIE),
                (None, {"name": "No id"}, SQUARE.buffer(0.01)),
                ("pa-1", {"name": "Same id, other area"}, SQUARE.buffer(0.02)),
                ("pa-3", {"name": "Swapped"}, Polygon([(8.0, 80.7), (8.1, 80.7), (8.1, 80.8), (8.0, 80.7)])),
                ("pa-4", {"name": "A line"}, LineString([(80.7, 8.0), (80.8, 8.1)])),
                ("pa-5", {}, SQUARE.buffer(0.03)),
                ("pa-6", {"name": "Twin"}, SQUARE),
            ],
            notes=[Note("transform.skipped", "a note from the adapter", "pa-9")],
        ),
        layer="ref.protected_area",
        expectations=QaExpectations(),
        service_area=SERVICE_AREA,
    )
    checks = {(item.check, item.severity, item.source_feature_id) for item in result.findings}
    assert ("geometry.invalid", "warning", "pa-2") in checks
    assert ("identifier.missing", "warning", None) in checks
    assert ("identifier.duplicate", "warning", "pa-1") in checks
    assert ("geometry.type", "warning", "pa-4") in checks
    assert ("identifier.name_missing", "warning", "pa-5") in checks
    assert ("duplicate.geometry", "warning", "pa-6") in checks
    assert ("transform.skipped", "info", "pa-9") in checks
    swapped = next(item for item in result.findings if item.check == "outlier.service_area")
    assert "swapped" in swapped.message
    # The invalid polygon is kept: the database repairs it and logs the original.
    assert sorted(result.frame["id"]) == ["pa-1", "pa-2", "pa-6"]
    rejected = next(item for item in result.findings if item.check == "outlier.rejected")
    assert rejected.severity == "error"  # 5 of 8 left out, above the 1 % allowed
    assert result.status == "failed"


def test_file_qa_checks_counts_and_extents() -> None:
    far = Point(81.9, 9.8)
    result = file_qa.check(
        extracted([("s-1", {"name": "Habarana"}, Point(80.75, 8.04)), ("s-2", {"name": "Far"}, far)]),
        layer="ref.settlement",
        expectations=QaExpectations(expected_bbox=(80.45, 7.75, 81.10, 8.30), min_features=3),
        service_area=SERVICE_AREA,
    )
    checks = {(item.check, item.severity) for item in result.findings}
    assert ("outlier.extent", "error") in checks
    assert ("outlier.count", "error") in checks
    assert result.status == "failed"


def test_file_qa_passes_clean_data() -> None:
    result = file_qa.check(
        extracted([("s-1", {"name": "Habarana"}, Point(80.75, 8.04))]),
        layer="ref.settlement",
        expectations=QaExpectations(expected_bbox=(80.45, 7.75, 81.10, 8.30)),
        service_area=SERVICE_AREA,
    )
    assert result.status == "passed"
    assert [item.check for item in result.findings] == ["crs.operation"]


# --- deterministic output -----------------------------------------------------------------------------------


def test_the_same_features_give_the_same_bytes(tmp_path: Path) -> None:
    rows = [
        ("b", {"name": "B", "population": None, "zeta": 1}, Point(80.123456789, 8.1)),
        ("a", {"name": "A"}, SQUARE),
    ]
    frame = gpd.GeoDataFrame(
        {"id": [row[0] for row in rows], "properties": [row[1] for row in rows]},
        geometry=[row[2] for row in rows],
        crs=4326,
    )
    reversed_frame = frame.iloc[::-1].reset_index(drop=True)
    first = writer.write(tmp_path / "one.geojson.gz", writer.feature_collection(frame))
    second = writer.write(tmp_path / "two.geojson.gz", writer.feature_collection(reversed_frame))
    assert first == second
    assert (tmp_path / "one.geojson.gz").read_bytes() == (tmp_path / "two.geojson.gz").read_bytes()
    content = gzip.decompress((tmp_path / "one.geojson.gz").read_bytes()).decode("utf-8")
    # Sorted by id, null properties left out, coordinates rounded to 7 decimals (about 1 cm).
    assert content.index('"id":"a"') < content.index('"id":"b"')
    assert "population" not in content
    assert "80.1234568" in content
