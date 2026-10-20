"""Contracts between the Python layers and the database model that need no database."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

import pytest
import shapely
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import TSTZRANGE

from app.core.config import DEFAULT_ALEMBIC_CONFIG, DEFAULT_SERVICE_AREA_BBOX, REPOSITORY_ROOT
from app.core.errors import GisValidationError
from app.core.tenancy import TenantId
from app.models import Base
from app.repositories.spatial_lookup import AdminAreaRow
from app.schemas.events import EventLocationIn
from app.schemas.geo_context import CONTEXT_REFERENCE_LAYERS, GeoContext
from app.schemas.reference_data import RELEASE_CODE_PATTERN, Manifest
from app.services.enrichment import GeoContextLimits, build_admin_hierarchy, reference_point_wkb
from app.services.reference_loader import LAYERS, _coerce

MIGRATIONS = REPOSITORY_ROOT / "db" / "migrations"
FIXTURES = REPOSITORY_ROOT / "data" / "fixtures"


def load_revision(name: str) -> ModuleType:
    if str(MIGRATIONS) not in sys.path:
        sys.path.insert(0, str(MIGRATIONS))
    path = next((MIGRATIONS / "versions").glob(f"*{name}*.py"))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def area(level: int, code: str) -> AdminAreaRow:
    names = {1: "province", 2: "district", 3: "ds_division", 4: "gn_division"}
    return AdminAreaRow(uuid.uuid4(), code, f"Area {code}", None, None, level, names[level])


# --- constants shared with the migrations -----------------------------------------------------------------


def test_database_envelope_equals_the_default_service_area() -> None:
    revision = load_revision("0002")
    assert (
        revision.MIN_LON,
        revision.MIN_LAT,
        revision.MAX_LON,
        revision.MAX_LAT,
    ) == DEFAULT_SERVICE_AREA_BBOX


def test_geo_context_document_has_exactly_the_keys_the_database_requires() -> None:
    revision = load_revision("0006")
    fields = {info.alias or name for name, info in GeoContext.model_fields.items()}
    assert set(revision.GEO_CONTEXT_KEYS) == fields
    assert set(revision.ARRAY_KEYS) <= fields
    assert revision.CONTEXT_REFERENCE_LAYERS == CONTEXT_REFERENCE_LAYERS


def test_document_layout_downgrade_restores_the_previous_constraint() -> None:
    assert load_revision("0006").PREVIOUS_GEO_CONTEXT_KEYS == load_revision("0005").GEO_CONTEXT_KEYS


def test_release_code_pattern_matches_the_database() -> None:
    revision = load_revision("0002")
    assert revision.RELEASE_CODE_PATTERN == RELEASE_CODE_PATTERN


def test_loader_layers_are_the_reference_tables() -> None:
    revision = load_revision("0003")
    assert set(LAYERS) == {layer.code for layer in revision.LAYERS}
    assert set(LAYERS) | {"ref.area_part"} == {
        name for name in Base.metadata.tables if name.startswith("ref.")
    }


def test_no_alerting_tables_are_modelled() -> None:
    forbidden = ("alert", "notif", "recipient", "subscriber")
    assert not [name for name in Base.metadata.tables if any(word in name for word in forbidden)]


# --- admin hierarchy --------------------------------------------------------------------------------------


def test_admin_hierarchy_inside_one_area_per_level() -> None:
    hierarchy = build_admin_hierarchy([area(1, "P1"), area(2, "D1"), area(3, "S1"), area(4, "G1")])
    assert hierarchy.on_boundary is False
    assert hierarchy.province is not None
    assert hierarchy.gn_division is not None
    assert (hierarchy.province.code, hierarchy.gn_division.code) == ("P1", "G1")
    assert hierarchy.codes.model_dump() == {"l1": "P1", "l2": "D1", "l3": "S1", "l4": "G1"}


def test_admin_hierarchy_on_a_shared_boundary_picks_the_lowest_code() -> None:
    hierarchy = build_admin_hierarchy([area(1, "P1"), area(2, "D2"), area(2, "D1")])
    assert hierarchy.on_boundary is True
    assert hierarchy.district is not None
    assert hierarchy.district.code == "D1"
    assert hierarchy.ds_division is None


def test_admin_hierarchy_outside_every_area() -> None:
    hierarchy = build_admin_hierarchy([])
    assert (hierarchy.province, hierarchy.district, hierarchy.on_boundary) == (None, None, False)
    assert hierarchy.codes.model_dump() == {"l1": None, "l2": None, "l3": None, "l4": None}


def test_admin_hierarchy_ignores_the_country_level() -> None:
    hierarchy = build_admin_hierarchy(
        [area(1, "P1"), AdminAreaRow(uuid.uuid4(), "LK", "Sri Lanka", None, None, 0, "country")]
    )
    assert hierarchy.on_boundary is False
    assert hierarchy.province is not None


def test_reference_point_of_a_concave_area_lies_inside_it() -> None:
    horseshoe = shapely.from_wkt(
        "POLYGON((80 8, 80.3 8, 80.3 8.3, 80.2 8.3, 80.2 8.1, 80.1 8.1, 80.1 8.3, 80 8.3, 80 8))"
    )
    assert not horseshoe.contains(horseshoe.centroid)
    point = shapely.from_wkb(reference_point_wkb(shapely.to_wkb(horseshoe)))
    assert horseshoe.contains(point)
    line = shapely.LineString([(80, 8), (80.1, 8.1)])
    assert line.intersects(shapely.from_wkb(reference_point_wkb(shapely.to_wkb(line))))


@pytest.mark.parametrize(
    "limits",
    [{"settlement_radius_m": 0}, {"road_radius_m": -1}, {"device_radius_m": 100_001}, {"device_limit": 51}],
)
def test_search_limits_are_bounded(limits: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"radii|device_limit"):
        GeoContextLimits(**limits)


# --- event intake -----------------------------------------------------------------------------------------


def event(**fields: Any) -> dict[str, Any]:
    return {
        "eventId": "evt-1",
        "tenantId": "tenant-a",
        "observedAt": "2026-09-10T10:00:00+05:30",
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": {"type": "Point", "coordinates": [80.75, 8.03]},
        **fields,
    }


def test_event_location_is_parsed_with_timezone() -> None:
    parsed = EventLocationIn.model_validate(event())
    assert parsed.observed_at == datetime(2026, 9, 10, 4, 30, tzinfo=UTC)
    assert parsed.observed_at.utcoffset() == timedelta(0), "normalised to UTC"


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"observedAt": "2026-09-10T10:00:00"}, "timezone"),
        ({"eventType": "Elephant Detected"}, "pattern"),
        ({"eventId": "has spaces"}, "pattern"),
        ({"locationSource": "device"}, "requires deviceId"),
        ({"location": None}, "location is required"),
        ({"sourceType": "device"}, "requires deviceId"),
        ({"fieldOfViewId": str(uuid.uuid4())}, "requires deviceId"),
        ({"locationAccuracyM": 0}, "greater than 0"),
        ({"location": {"type": "GeometryCollection", "coordinates": [1]}}, r"literal_error|Input should be"),
        ({"recipients": ["someone"]}, "Extra inputs"),
        ({"geometry": {"type": "Point", "coordinates": [80.75, 8.03]}}, "Extra inputs"),
        ({"tenantId": "Tenant A"}, "pattern"),
        ({"tenantId": None}, "string_type|Input should be a valid string"),
        ({"metadata": {"blob": "x" * 20_000}}, "must not exceed"),
        ({"metadata": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": 1}}}}}}}}}}, "nested deeper"),
        ({"metadata": ["not", "an", "object"]}, "dict_type|valid dictionary"),
    ],
)
def test_invalid_event_locations_are_rejected(fields: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        EventLocationIn.model_validate(event(**fields))


def test_device_events_may_omit_the_geometry() -> None:
    parsed = EventLocationIn.model_validate(
        event(location=None, sourceType="device", locationSource="device", deviceId=str(uuid.uuid4()))
    )
    assert parsed.location is None


def test_event_metadata_is_kept_as_sent() -> None:
    metadata = {"confidence": 0.93, "labels": ["elephant", "calf"], "frame": {"index": 17}}
    assert EventLocationIn.model_validate(event(metadata=metadata)).metadata == metadata
    tenant = TenantId(EventLocationIn.model_validate(event()).tenant_id)
    assert tenant.value == "tenant-a"


# --- reference data manifests -----------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["lka_open", "synthetic_habarana"])
def test_fixture_manifests_are_complete(fixture: str) -> None:
    path = FIXTURES / fixture / "manifest.json"
    manifest = Manifest.read(path)
    sources = {source.code for source in manifest.sources}
    for spec in manifest.files:
        file = path.parent / spec.path
        assert file.is_file(), spec.path
        assert spec.source in sources
        collection = json.loads(file.read_text(encoding="utf-8"))
        ids = [feature["id"] for feature in collection["features"]]
        assert len(ids) == len(set(ids)), f"duplicate feature ids in {spec.path}"
    assert all(source.commercial_use_allowed or source.permission_reference for source in manifest.sources)


def test_open_data_sources_record_attribution_and_licence() -> None:
    manifest = Manifest.read(FIXTURES / "lka_open" / "manifest.json")
    for source in manifest.sources:
        assert source.attribution
        assert source.licence_url
    assert (FIXTURES / "lka_open" / "SOURCES.md").is_file()


def test_range_properties_are_converted() -> None:
    value = _coerce("valid_during", TSTZRANGE(), "[2025-10-01 00:00:00+05:30,2026-01-01 00:00:00+05:30)")
    assert value.lower == datetime(2025, 9, 30, 18, 30, tzinfo=UTC)
    assert value.bounds == "[)"
    unbounded = _coerce("valid_during", TSTZRANGE(), "(,2026-01-01T00:00:00Z]")
    assert unbounded.lower is None
    assert unbounded.bounds == "(]"


@pytest.mark.parametrize("text", ["2025-10-01", "[2025-10-01,2026-01-01)", "[a,b)"])
def test_invalid_range_properties_are_rejected(text: str) -> None:
    with pytest.raises(GisValidationError):
        _coerce("valid_during", TSTZRANGE(), text)


def test_non_string_properties_are_left_alone() -> None:
    assert _coerce("severity", TSTZRANGE(), 3) == 3
    assert _coerce("name", TSTZRANGE(), None) is None


# --- offline migration script ------------------------------------------------------------------------------


@pytest.mark.parametrize(("revisions", "action"), [("base:head", "upgrade"), ("head:base", "downgrade")])
def test_offline_migration_script_can_be_generated(revisions: str, action: str) -> None:
    """``alembic upgrade --sql`` produces the script a DBA reviews; PL/pgSQL '%' must not be escaped."""
    buffer = io.StringIO()
    config = Config(str(DEFAULT_ALEMBIC_CONFIG), output_buffer=buffer)
    config.attributes["skip_logging_config"] = True
    getattr(command, action)(config, revisions, sql=True)
    script = buffer.getvalue()
    assert "%%" not in script
    assert "RAISE EXCEPTION 'bearing must be in [0, 360) degrees, got %'" in script or action == "downgrade"
    expected = "CREATE TABLE geo.event_location" if action == "upgrade" else "DROP TABLE geo.event_location"
    assert expected in script
    assert "notification" not in script.lower()


def test_leakproof_statement_is_applied_by_the_container_initialisation() -> None:
    statement = "ALTER FUNCTION public.geometry_overlaps(public.geometry, public.geometry) LEAKPROOF;"
    admin_script = (REPOSITORY_ROOT / "db" / "admin" / "postgis-leakproof.sql").read_text(encoding="utf-8")
    init_script = (REPOSITORY_ROOT / "db" / "init" / "20-gis-roles-and-databases.sh").read_text(
        encoding="utf-8"
    )
    assert statement in admin_script
    assert statement in init_script
