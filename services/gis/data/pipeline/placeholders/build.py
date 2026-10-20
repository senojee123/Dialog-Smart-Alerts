"""Build the development placeholder risk zones (``dev_risk_zones.geojson``).

Sri Lanka has no openly licensed source for risk zones: elephant corridors come from the Department of
Wildlife Conservation, flood zones from the Disaster Management Centre and the Irrigation Department,
landslide zones from NBRO - all under agreement. So that the application can be run locally end to end
(zone hits in geo-context, the risk zone layer on the map), the development profile uses these
**placeholders**: artificial shapes (straight corridors, circles, a hexagon, a box) near Habarana, every
name starting with "DEV PLACEHOLDER", marked ``placeholder = true`` and loaded with
``geometry_source = synthetic``. They say nothing about real hazards. The pipeline refuses them in a
production profile and the database QA refuses synthetic features in a production release.

Run from ``backend/`` (needs Shapely and pyproj)::

    python ../data/pipeline/placeholders/build.py
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely import LineString, Point, Polygon, box
from shapely.geometry import mapping
from shapely.ops import transform

HERE = Path(__file__).resolve().parent
NOTE = "Development placeholder: an artificial shape, not a real risk zone"
TO_METRIC = Transformer.from_crs(4326, 5235, always_xy=True).transform
TO_WGS84 = Transformer.from_crs(5235, 4326, always_xy=True).transform


def corridor(start: tuple[float, float], end: tuple[float, float], width_m: float) -> Polygon:
    line = transform(TO_METRIC, LineString([start, end]))
    return transform(TO_WGS84, line.buffer(width_m / 2, cap_style="flat"))


def circle(centre: tuple[float, float], radius_m: float) -> Polygon:
    return transform(TO_WGS84, transform(TO_METRIC, Point(centre)).buffer(radius_m, quad_segs=16))


def hexagon(centre: tuple[float, float], radius_m: float) -> Polygon:
    x, y = TO_METRIC(*centre)
    corners = [
        (x + radius_m * math.cos(math.radians(60 * i)), y + radius_m * math.sin(math.radians(60 * i)))
        for i in range(6)
    ]
    return transform(TO_WGS84, Polygon(corners))


def rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 7)
    if isinstance(value, list | tuple):
        return [rounded(item) for item in value]
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    return value


ZONES = [
    (
        "RZ-DEV-1",
        corridor((80.72, 8.00), (80.78, 8.07), 1_000),
        {"name": "DEV PLACEHOLDER elephant corridor A", "risk_type": "elephant_corridor", "severity": 5},
    ),
    (
        "RZ-DEV-2",
        corridor((80.78, 8.05), (80.93, 8.02), 1_200),
        {"name": "DEV PLACEHOLDER elephant corridor B", "risk_type": "elephant_corridor", "severity": 4},
    ),
    (
        "RZ-DEV-3",
        circle((80.99, 7.95), 3_000),
        {
            "name": "DEV PLACEHOLDER flood zone",
            "risk_type": "flood",
            "severity": 3,
            # A north-east monsoon season: exercises time-dependent zones.
            "valid_during": "[2026-10-01 00:00:00+05:30,2027-02-01 00:00:00+05:30)",
        },
    ),
    (
        "RZ-DEV-4",
        hexagon((80.62, 7.82), 2_000),
        {"name": "DEV PLACEHOLDER landslide zone", "risk_type": "landslide", "severity": 2},
    ),
    (
        "RZ-DEV-5",
        box(80.50, 8.15, 80.70, 8.28),
        {"name": "DEV PLACEHOLDER drought zone", "risk_type": "drought", "severity": 2},
    ),
]


def main() -> int:
    features = [
        {
            "type": "Feature",
            "properties": {"id": identifier, **properties, "placeholder": True, "note": NOTE},
            "geometry": rounded(mapping(geometry)),
        }
        for identifier, geometry, properties in ZONES
    ]
    text = json.dumps({"type": "FeatureCollection", "features": features}, indent=1) + "\n"
    target = HERE / "dev_risk_zones.geojson"
    target.write_text(text, encoding="utf-8")
    print(f"{target.name} {hashlib.sha256(text.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
