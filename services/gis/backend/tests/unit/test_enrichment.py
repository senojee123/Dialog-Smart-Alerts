"""Enrichment engine parts that need no database: validation, document assembly, examples."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import shapely

from app.api.v1.enrichment_examples import REQUEST_EXAMPLES, RESPONSE_EXAMPLE
from app.core.config import DEFAULT_SERVICE_AREA_BBOX
from app.core.errors import CoordinateError, GisValidationError, InvalidGeometryError
from app.repositories.events import StoredEventLocation
from app.repositories.spatial_lookup import (
    AdminAreaRow,
    ContextLookupResult,
    DeviceRow,
    GeofenceHitRow,
    ReleaseRow,
    RoadRow,
    SettlementRow,
    ZoneRow,
)
from app.schemas.events import EventLocationIn
from app.schemas.geo_context import GeoContext
from app.services.enrichment import MAX_CLOCK_SKEW, GeoContextLimits, validate_event
from app.services.enrichment.assembly import assemble_geo_context, geo_context_record, metres
from app.spatial.service_area import ServiceArea

AREA = ServiceArea.from_bbox(DEFAULT_SERVICE_AREA_BBOX)
NOW = datetime(2026, 9, 17, 6, 0, tzinfo=UTC)
# Keys of the plan's geo-context block (plan §5.3) plus the members this implementation adds.
PLAN_KEYS = {
    "schema",
    "locationSource",
    "admin",
    "nearestSettlement",
    "nearestRoad",
    "insideZones",
    "geofenceHits",
    "nearestDevices",
    "refDataRelease",
    "computedAt",
}
ADDED_KEYS = {"eventId", "tenantId", "observedAt", "geometryKind", "missingLayers", "search"}


def event(**fields: Any) -> EventLocationIn:
    data: dict[str, Any] = {
        "eventId": "evt-1",
        "tenantId": "tenant-a",
        "observedAt": NOW.isoformat(),
        "eventType": "wildlife.elephant_detected",
        "sourceType": "sensor",
        "locationSource": "sensor",
        "location": {"type": "Point", "coordinates": [80.75, 8.03]},
    }
    data.update(fields)
    return EventLocationIn.model_validate(data)


# --- validation ------------------------------------------------------------------------------------------


def test_valid_event_yields_tenant_and_geometry() -> None:
    validated = validate_event(event(), service_area=AREA, now=NOW)
    assert validated.tenant.value == "tenant-a"
    assert validated.geometry is not None
    assert validated.geometry.geometry.equals(shapely.Point(80.75, 8.03))


def test_device_events_without_location_are_resolved_later() -> None:
    device_event = event(
        location=None, sourceType="device", locationSource="device", deviceId=str(uuid.uuid4())
    )
    assert validate_event(device_event, service_area=AREA, now=NOW).geometry is None


@pytest.mark.parametrize(
    ("ahead", "accepted"),
    [(timedelta(0), True), (MAX_CLOCK_SKEW, True), (MAX_CLOCK_SKEW + timedelta(seconds=1), False)],
)
def test_observation_time_may_lead_by_the_clock_skew_only(ahead: timedelta, accepted: bool) -> None:
    candidate = event(observedAt=(NOW + ahead).isoformat())
    if accepted:
        validate_event(candidate, service_area=AREA, now=NOW)
        return
    with pytest.raises(GisValidationError, match="future") as info:
        validate_event(candidate, service_area=AREA, now=NOW)
    assert info.value.extensions["maxClockSkewS"] == 86_400


@pytest.mark.parametrize(
    ("location", "error", "extensions"),
    [
        ({"type": "Point", "coordinates": [8.03, 80.75]}, CoordinateError, {"likelySwapped": True}),
        ({"type": "Point", "coordinates": [80.27, 13.08]}, CoordinateError, {"path": "coordinates"}),
        ({"type": "Point", "coordinates": [181.0, 8.0]}, CoordinateError, {"path": "coordinates"}),
        ({"type": "Point", "coordinates": [80.75, float("nan")]}, CoordinateError, {}),
        ({"type": "Point", "coordinates": [80.75]}, InvalidGeometryError, {}),
        ({"type": "LineString", "coordinates": [[80.75, 8.03]]}, InvalidGeometryError, {}),
        (
            {"type": "Polygon", "coordinates": [[[80.7, 8.0], [80.8, 8.0], [80.8, 8.1], [80.7, 8.1]]]},
            InvalidGeometryError,
            {},
        ),
        (
            {
                "type": "Polygon",
                "coordinates": [[[80.70, 8.0], [80.8, 8.1], [80.8, 8.0], [80.7, 8.1], [80.70, 8.0]]],
            },
            InvalidGeometryError,
            {"reason": "Self-intersection[80.75 8.05]"},
        ),
    ],
)
def test_unacceptable_locations_are_rejected_with_details(
    location: dict[str, Any], error: type[Exception], extensions: dict[str, Any]
) -> None:
    with pytest.raises(error) as info:
        validate_event(event(location=location), service_area=AREA, now=NOW)
    raised = info.value
    assert isinstance(raised, GisValidationError)
    assert extensions.items() <= raised.extensions.items()


def test_the_service_area_setting_narrows_what_is_accepted() -> None:
    habarana_only = ServiceArea.from_bbox((80.6, 7.9, 80.9, 8.2))
    validate_event(event(), service_area=habarana_only, now=NOW)
    with pytest.raises(CoordinateError, match="outside the service area"):
        validate_event(
            event(location={"type": "Point", "coordinates": [79.86, 6.93]}),
            service_area=habarana_only,
            now=NOW,
        )


# --- document assembly -----------------------------------------------------------------------------------

RELEASE = ReleaseRow(uuid.UUID("0192f1a0-0000-7000-8000-000000000001"), "ref-2026.09-test", "published")
LOCATION = StoredEventLocation(
    tenant_id="tenant-a",
    event_id="evt-1",
    observed_at=NOW,
    event_type="wildlife.elephant_detected",
    location_source="sensor",
    geometry_kind="point",
    geometry_wkb=shapely.to_wkb(shapely.Point(80.75, 8.03)),
    device_id=None,
    field_of_view_id=None,
    location_accuracy_m=None,
)


def _uuid(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


LOOKUP = ContextLookupResult(
    release=RELEASE,
    admin_areas=(
        AdminAreaRow(_uuid(1), "P1", "Province", "පළාත", "மாகாணம்", 1, "province"),
        AdminAreaRow(_uuid(2), "D1", "District", None, None, 2, "district"),
    ),
    settlement=SettlementRow(_uuid(3), "Town", None, None, "town", "footprint", 499.994999),
    road=RoadRow(_uuid(4), "A11", "A", "A11", 500.005001),
    zones=(ZoneRow("protected_area", _uuid(5), "Park", "National Park", None, "within"),),
    geofences=(GeofenceHitRow(_uuid(6), "Fence", "circle", "tenant-b", 3, "within"),),
    devices=(DeviceRow(_uuid(7), "Camera", "camera", "tenant-a", 12.3456, True),),
    missing_layers=("risk_zone",),
)


def test_assembled_document_has_the_requested_shape() -> None:
    context = assemble_geo_context(LOCATION, LOOKUP, RELEASE, GeoContextLimits(), computed_at=NOW)
    document = context.model_dump(mode="json", by_alias=True)
    assert set(document) == PLAN_KEYS | ADDED_KEYS
    assert document["schema"] == "geo-context/1"
    assert document["refDataRelease"] == "ref-2026.09-test"
    assert document["admin"]["codes"] == {"l1": "P1", "l2": "D1", "l3": None, "l4": None}
    assert document["admin"]["province"]["nameSi"] == "පළාත"
    assert document["nearestSettlement"]["basis"] == "footprint"
    assert document["nearestRoad"]["class"] == "A"
    assert document["insideZones"] == [
        {
            "id": str(_uuid(5)),
            "type": "protected_area",
            "name": "Park",
            "category": "National Park",
            "severity": None,
            "relation": "within",
        }
    ]
    assert document["geofenceHits"][0]["tenantId"] == "tenant-b"
    assert document["nearestDevices"][0] == {
        "deviceId": str(_uuid(7)),
        "name": "Camera",
        "deviceType": "camera",
        "tenantId": "tenant-a",
        "distanceM": 12.35,
        "inFieldOfView": True,
    }
    assert document["missingLayers"] == ["risk_zone"]
    assert document["search"] == {
        "settlementRadiusM": 25_000.0,
        "roadRadiusM": 10_000.0,
        "deviceRadiusM": 5_000.0,
        "deviceLimit": 5,
    }


def test_distances_are_rounded_to_centimetres() -> None:
    context = assemble_geo_context(LOCATION, LOOKUP, RELEASE, GeoContextLimits(), computed_at=NOW)
    assert context.nearest_settlement is not None
    assert context.nearest_road is not None
    assert (context.nearest_settlement.distance_m, context.nearest_road.distance_m) == (499.99, 500.01)
    assert metres(500.0) == 500.0
    assert metres(0.004) == 0.0


def test_assembly_is_deterministic_and_round_trips() -> None:
    first = assemble_geo_context(LOCATION, LOOKUP, RELEASE, GeoContextLimits(), computed_at=NOW)
    second = assemble_geo_context(LOCATION, LOOKUP, RELEASE, GeoContextLimits(), computed_at=NOW)
    assert first == second
    text = first.model_dump_json(by_alias=True)
    assert GeoContext.model_validate_json(text) == first
    assert json.loads(text) == json.loads(second.model_dump_json(by_alias=True))


def test_stored_row_mirrors_the_document() -> None:
    context = assemble_geo_context(LOCATION, LOOKUP, RELEASE, GeoContextLimits(), computed_at=NOW)
    record = geo_context_record(context, RELEASE)
    assert record.release_id == RELEASE.id
    assert record.admin_codes == ("P1", "D1", None, None)
    assert record.admin_ids == (_uuid(1), _uuid(2), None, None)
    assert record.nearest_settlement_distance_m == 499.99
    assert record.zone_hits == (("protected_area", _uuid(5), "within"),)
    assert record.geofence_hits == ((_uuid(6), "tenant-b", 3, "within"),)
    assert record.document["eventId"] == "evt-1"
    assert record.document["tenantId"] == "tenant-a"


def test_empty_lookup_gives_an_empty_but_complete_document() -> None:
    empty = ContextLookupResult(
        release=RELEASE,
        admin_areas=(),
        settlement=None,
        road=None,
        zones=(),
        geofences=(),
        devices=(),
        missing_layers=("admin_area", "settlement", "road", "protected_area", "risk_zone"),
    )
    document = assemble_geo_context(LOCATION, empty, RELEASE, GeoContextLimits(), computed_at=NOW).model_dump(
        mode="json", by_alias=True
    )
    assert set(document) == PLAN_KEYS | ADDED_KEYS
    assert document["admin"]["province"] is None
    assert (document["nearestSettlement"], document["nearestRoad"]) == (None, None)
    assert document["insideZones"] == document["geofenceHits"] == document["nearestDevices"] == []


# --- OpenAPI examples ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REQUEST_EXAMPLES))
def test_request_examples_are_valid_events(name: str) -> None:
    parsed = EventLocationIn.model_validate(REQUEST_EXAMPLES[name]["value"])
    if parsed.location is not None:
        validate_event(parsed, service_area=AREA, now=parsed.observed_at)


def test_response_example_is_a_valid_document() -> None:
    context = GeoContext.model_validate(RESPONSE_EXAMPLE)
    assert set(RESPONSE_EXAMPLE) == PLAN_KEYS | ADDED_KEYS
    assert context.event_id == REQUEST_EXAMPLES["point"]["value"]["eventId"]
