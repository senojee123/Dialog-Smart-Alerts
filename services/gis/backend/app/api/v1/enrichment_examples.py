"""OpenAPI examples for ``POST /geo/v1/enrich``.

``RESPONSE_EXAMPLE`` is regenerated from a real run, not written by hand:
``tests/integration/test_enrich_api.py::test_openapi_response_example_is_a_real_result`` enriches the
first request example against the open-data fixture (``data/fixtures/lka_open``) and compares.
"""

from __future__ import annotations

from typing import Any, Final

REQUEST_EXAMPLES: Final[dict[str, dict[str, Any]]] = {
    "point": {
        "summary": "Point observed by a sensor",
        "value": {
            "eventId": "evt-2026-09-000123",
            "tenantId": "wildlife-dept",
            "observedAt": "2026-09-14T08:32:10+05:30",
            "eventType": "wildlife.elephant_detected",
            "sourceType": "sensor",
            "sourceRef": "seismic-array-7",
            "location": {"type": "Point", "coordinates": [80.749, 8.037]},
            "locationSource": "sensor",
            "locationAccuracyM": 25,
            "metadata": {"confidence": 0.93, "herdSize": 4},
        },
    },
    "device": {
        "summary": "Camera event located at the camera",
        "value": {
            "eventId": "evt-2026-09-000124",
            "tenantId": "wildlife-dept",
            "observedAt": "2026-09-14T08:35:00+05:30",
            "eventType": "wildlife.elephant_detected",
            "sourceType": "device",
            "deviceId": "01963b7e-8a1c-7c3e-9f2a-3b5d7e9f1a2c",
            "locationSource": "device",
        },
    },
    "line": {
        "summary": "Estimated track (line event)",
        "value": {
            "eventId": "evt-2026-09-000125",
            "tenantId": "wildlife-dept",
            "observedAt": "2026-09-14T09:00:00+05:30",
            "eventType": "wildlife.herd_movement",
            "sourceType": "external",
            "location": {"type": "LineString", "coordinates": [[80.745, 8.030], [80.752, 8.041]]},
            "locationSource": "estimated",
            "locationAccuracyM": 150,
        },
    },
}

RESPONSE_EXAMPLE: Final[dict[str, Any]] = {
    "schema": "geo-context/1",
    "eventId": "evt-2026-09-000123",
    "tenantId": "wildlife-dept",
    "observedAt": "2026-09-14T03:02:10Z",
    "locationSource": "sensor",
    "geometryKind": "point",
    "admin": {
        "province": {
            "id": "01a0ae42-9a49-7bd7-b3bd-b96054154add",
            "code": "LK-7",
            "name": "North Central Province",
            "nameSi": None,
            "nameTa": None,
            "level": 1,
            "levelName": "province",
        },
        "district": {
            "id": "01a0ae42-9a90-7c11-b616-c24be9d113fa",
            "code": "LK-71",
            "name": "Anuradhapura District",
            "nameSi": None,
            "nameTa": None,
            "level": 2,
            "levelName": "district",
        },
        "dsDivision": {
            "id": "01a0ae42-9b05-7168-8db5-771f9535e68c",
            "code": "8540358B75401696350617",
            "name": "Palugaswewa",
            "nameSi": None,
            "nameTa": None,
            "level": 3,
            "levelName": "ds_division",
        },
        "gnDivision": {
            "id": "01a0ae42-9b26-7f79-818d-d7699bef9f47",
            "code": "91002919B21028929510394",
            "name": "Habarana",
            "nameSi": None,
            "nameTa": None,
            "level": 4,
            "levelName": "gn_division",
        },
        "codes": {
            "l1": "LK-7",
            "l2": "LK-71",
            "l3": "8540358B75401696350617",
            "l4": "91002919B21028929510394",
        },
        "onBoundary": False,
    },
    "nearestSettlement": {
        "id": "01a0ae42-9b50-7ab3-aad2-604be3734276",
        "name": "Anuradhapura",
        "nameSi": None,
        "nameTa": None,
        "settlementType": "city",
        "basis": "point",
        "distanceM": 53118.95,
    },
    "nearestRoad": {
        "id": "01a0ae42-9b69-76b0-9057-f78209ce83ba",
        "name": None,
        "class": "unknown",
        "refCode": None,
        "distanceM": 287.87,
    },
    "insideZones": [],
    "geofenceHits": [
        {
            "id": "01a0ae42-9c57-77db-b29a-82335bcc7cce",
            "name": "Habarana junction watch zone",
            "kind": "circle",
            "tenantId": "wildlife-dept",
            "version": 1,
            "relation": "within",
        }
    ],
    "nearestDevices": [
        {
            "deviceId": "01a0ae42-9c55-71cc-b20a-97b06881fc8f",
            "name": "HB-CAM-01",
            "deviceType": "camera",
            "tenantId": "wildlife-dept",
            "distanceM": 468.41,
            "inFieldOfView": True,
        }
    ],
    "missingLayers": ["protected_area", "risk_zone"],
    "search": {
        "settlementRadiusM": 60000.0,
        "roadRadiusM": 10000.0,
        "deviceRadiusM": 5000.0,
        "deviceLimit": 5,
    },
    "refDataRelease": "ref-2026.09-lka-open",
    "computedAt": "2026-09-17T07:26:36.269681Z",
}
