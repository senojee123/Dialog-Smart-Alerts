"""Build the synthetic "fixture world" near Habarana.

Constructed geometry with exactly known relationships, for tests that need to know the right answer:
shared admin boundaries, a protected area with an enclave, a seasonal risk zone, a settlement
footprint, roads, a tank, and deliberately bad input (an invalid bow-tie polygon that the database
repairs, a facility outside Sri Lanka and one with swapped coordinates, both rejected by the loader).

Every name starts with "Fixture" and every row is marked ``geometry_source = synthetic``. The data is
loaded into its own release (``ref-2026.09-fixture``) so it never mixes with real reference data.

Run from ``backend/``::

    python ../data/fixtures/synthetic_habarana/build.py

Layout (WGS84 degrees; the whole world lies in lon 80.70-80.80, lat 7.98-8.08)::

    province  SYN-P1  80.70..80.80 x 7.98..8.08
    district  SYN-D1  80.70..80.75            SYN-D2  80.75..80.80    (shared edge lon 80.75)
    DS        SYN-S1  D1, lat 7.98..8.03      SYN-S2  D1, lat 8.03..8.08    SYN-S3 = D2
    GN        SYN-G1  S1, lon 80.700..80.725  SYN-G2  S1, lon 80.725..80.750
    centre    (80.75, 8.03) is on the D1/D2 edge and the S1/S2/S3 corner
    overlap   (80.758, 8.015) lies in the elephant corridor, the sanctuary and the drought zone
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from shapely import LineString, MultiLineString, Point, Polygon, box
from shapely.geometry import mapping

HERE = Path(__file__).resolve().parent
RELEASE = "ref-2026.09-fixture"
SOURCE = "gis-core-fixtures"


def feature(fid: str, geometry: Any, properties: dict[str, Any]) -> dict[str, Any]:
    geo = geometry if isinstance(geometry, dict) else mapping(geometry)
    return {"type": "Feature", "id": fid, "properties": properties, "geometry": geo}


ADMIN = {
    "admin_level1.geojson": [
        feature("SYN-P1", box(80.70, 7.98, 80.80, 8.08), {"name": "Fixture Province", "code": "SYN-P1"}),
    ],
    "admin_level2.geojson": [
        feature(
            "SYN-D1",
            box(80.70, 7.98, 80.75, 8.08),
            {"name": "Fixture West District", "code": "SYN-D1", "parent_code": "SYN-P1"},
        ),
        feature(
            "SYN-D2",
            box(80.75, 7.98, 80.80, 8.08),
            {"name": "Fixture East District", "code": "SYN-D2", "parent_code": "SYN-P1"},
        ),
    ],
    "admin_level3.geojson": [
        feature(
            "SYN-S1",
            box(80.70, 7.98, 80.75, 8.03),
            {"name": "Fixture South-West DS", "code": "SYN-S1", "parent_code": "SYN-D1"},
        ),
        feature(
            "SYN-S2",
            box(80.70, 8.03, 80.75, 8.08),
            {"name": "Fixture North-West DS", "code": "SYN-S2", "parent_code": "SYN-D1"},
        ),
        feature(
            "SYN-S3",
            box(80.75, 7.98, 80.80, 8.08),
            {"name": "Fixture East DS", "code": "SYN-S3", "parent_code": "SYN-D2"},
        ),
    ],
    "admin_level4.geojson": [
        feature(
            "SYN-G1",
            box(80.700, 7.98, 80.725, 8.03),
            {"name": "Fixture GN West", "code": "SYN-G1", "parent_code": "SYN-S1"},
        ),
        feature(
            "SYN-G2",
            box(80.725, 7.98, 80.750, 8.03),
            {"name": "Fixture GN East", "code": "SYN-G2", "parent_code": "SYN-S1"},
        ),
    ],
}

# A park with an enclave (hole): points in the enclave are outside the park.
PARK = Polygon(
    [(80.76, 8.04), (80.79, 8.04), (80.79, 8.07), (80.76, 8.07), (80.76, 8.04)],
    [[(80.77, 8.05), (80.77, 8.06), (80.78, 8.06), (80.78, 8.05), (80.77, 8.05)]],
)
# Self-intersecting "bow-tie": invalid; the database repairs it into two triangles and logs it.
BOW_TIE = {
    "type": "Polygon",
    "coordinates": [[[80.785, 7.985], [80.795, 7.995], [80.795, 7.985], [80.785, 7.995], [80.785, 7.985]]],
}

LAYERS: dict[str, list[dict[str, Any]]] = {
    **ADMIN,
    "protected_areas.geojson": [
        feature(
            "SYN-PA1",
            PARK,
            {
                "name": "Fixture National Park",
                "designation": "National Park",
                "managing_authority": "DWC",
                "iucn_category": "II",
            },
        ),
        feature(
            "SYN-PA2",
            BOW_TIE,
            {
                "name": "Fixture Bow-tie Reserve",
                "designation": "Forest Reserve",
                "managing_authority": "FD",
                "iucn_category": "not_reported",
            },
        ),
        # Overlaps the elephant corridor and the drought zone: (80.758, 8.015) lies in all three.
        feature(
            "SYN-PA3",
            box(80.755, 8.005, 80.765, 8.018),
            {
                "name": "Fixture Sanctuary",
                "designation": "Sanctuary",
                "managing_authority": "DWC",
                "iucn_category": "IV",
            },
        ),
    ],
    "risk_zones.geojson": [
        feature(
            "SYN-RZ1",
            box(80.74, 8.00, 80.76, 8.02),
            {"name": "Fixture Elephant Corridor", "risk_type": "elephant_corridor", "severity": 4},
        ),
        feature(
            "SYN-RZ2",
            box(80.70, 7.98, 80.72, 8.00),
            {
                "name": "Fixture Flood Zone",
                "risk_type": "flood",
                "severity": 3,
                # North-east monsoon season 2025 only (a closed period in the past, so tests can use it).
                "valid_during": "[2025-10-01 00:00:00+05:30,2026-01-01 00:00:00+05:30)",
            },
        ),
        feature(
            "SYN-RZ3",
            box(80.750, 8.012, 80.770, 8.025),
            {"name": "Fixture Drought Zone", "risk_type": "drought", "severity": 2},
        ),
    ],
    "settlements.geojson": [
        feature(
            "SYN-T1",
            box(80.745, 8.025, 80.755, 8.035),
            {"name": "Fixture Town", "settlement_type": "town", "population": 4200},
        ),
        feature("SYN-V1", Point(80.71, 8.06), {"name": "Fixture Village", "settlement_type": "village"}),
    ],
    "facilities.geojson": [
        feature(
            "SYN-F1",
            Point(80.746, 8.028),
            {"name": "Fixture Police Station", "facility_type": "police_station"},
        ),
        feature(
            "SYN-F2",
            Point(80.770, 8.035),
            {"name": "Fixture Wildlife Office", "facility_type": "wildlife_office"},
        ),
        # Rejected by the loader: outside the service area (Chennai).
        feature("SYN-F3", Point(80.27, 13.08), {"name": "Fixture Office Abroad", "facility_type": "other"}),
        # Rejected by the loader: latitude and longitude swapped.
        feature("SYN-F4", Point(8.03, 80.75), {"name": "Fixture Swapped Office", "facility_type": "other"}),
    ],
    "roads.geojson": [
        # Straight east-west road along latitude 8.01.
        feature(
            "SYN-R1",
            LineString([(80.70, 8.01), (80.80, 8.01)]),
            {"name": "Fixture Road", "road_class": "A", "ref_code": "A99"},
        ),
        feature(
            "SYN-R2",
            MultiLineString([[(80.73, 8.05), (80.73, 8.07)]]),
            {"name": "Fixture Track", "road_class": "track"},
        ),
    ],
    "water_bodies.geojson": [
        feature(
            "SYN-W1",
            box(80.705, 8.035, 80.715, 8.045),
            {"name": "Fixture Tank", "water_type": "tank"},
        ),
        feature(
            "SYN-W2",
            LineString([(80.78, 7.98), (80.78, 8.03)]),
            {"name": "Fixture Oya", "water_type": "stream"},
        ),
    ],
}

FILES = [
    ("admin_level1.geojson", "ref.admin_area", {"properties": {"level": 1}}),
    ("admin_level2.geojson", "ref.admin_area", {"properties": {"level": 2}, "parentBy": "code"}),
    ("admin_level3.geojson", "ref.admin_area", {"properties": {"level": 3}, "parentBy": "code"}),
    ("admin_level4.geojson", "ref.admin_area", {"properties": {"level": 4}, "parentBy": "code"}),
    ("protected_areas.geojson", "ref.protected_area", {}),
    ("risk_zones.geojson", "ref.risk_zone", {}),
    ("settlements.geojson", "ref.settlement", {"adminAreaBy": "location"}),
    # Two of the four facilities are rejected on purpose (outside the service area, swapped coordinates).
    ("facilities.geojson", "ref.facility", {"qa": {"maxRejectedRatio": 1.0}}),
    ("roads.geojson", "ref.road", {}),
    ("water_bodies.geojson", "ref.water_body", {}),
]


def main() -> int:
    outputs = {}
    for name, features in LAYERS.items():
        text = json.dumps({"type": "FeatureCollection", "features": features}, indent=1) + "\n"
        (HERE / name).write_text(text, encoding="utf-8")
        outputs[name] = hashlib.sha256(text.encode()).hexdigest()
    manifest = {
        "release": {
            "code": RELEASE,
            "purpose": "test",
            "description": "Synthetic fixture world near Habarana (tests only)",
        },
        "sources": [
            {
                "code": SOURCE,
                "name": "GIS Core Service synthetic test fixtures",
                "publisher": "GIS Core Service project",
                "licence": "CC0-1.0",
                "attribution": "Synthetic data; not a real place",
                "commercialUseAllowed": True,
                "redistributionAllowed": True,
                "notes": "Constructed geometry for automated tests. Not for operational use.",
            }
        ],
        "files": [
            {
                "path": path,
                "layer": layer,
                "source": SOURCE,
                "sourceReference": "data/fixtures/synthetic_habarana/build.py (constructed geometry)",
                "sourceVersion": "1",
                "transformation": "none: constructed in EPSG:4326",
                "geometrySource": "synthetic",
                "geometryAccuracyM": 0.01,
                **extra,
            }
            for path, layer, extra in FILES
        ],
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
