"""The ``placeholder`` adapter: labelled development placeholders, never real data.

Some layers have no openly licensed source for Sri Lanka (risk zones: elephant corridors, flood and
landslide zones come from DWC, DMC and NBRO under agreement). So that the whole application can run
locally, the development profile fills them with *placeholders*: obviously artificial shapes (straight
corridors, circles, boxes) whose every name starts with ``DEV PLACEHOLDER``, marked
``geometry_source = synthetic`` and ``placeholder = true``. This adapter refuses a file that does not
carry those labels on every feature; the licence checks refuse the adapter in production profiles, and
the database QA refuses synthetic features in a production release.

The file (GeoJSON, EPSG:4326) already uses the layer's column names; it is copied, not transformed.
"""

from __future__ import annotations

from typing import Any, Final

import pyogrio

from app.pipeline.acquire import AcquiredSource
from app.pipeline.adapters import BuildContext, Extracted
from app.pipeline.crs import choose_operation
from app.pipeline.errors import PipelineError
from app.pipeline.features import clean, frame, select_area, text
from app.pipeline.profile import DatasetConfig, SourceConfig

LABEL: Final = "DEV PLACEHOLDER"


def extract(
    context: BuildContext, dataset: DatasetConfig, source: SourceConfig, acquired: AcquiredSource
) -> Extracted:
    if context.profile.profile.purpose == "production":
        raise PipelineError(f"dataset {dataset.name}: placeholders cannot be built for a production release")
    data = pyogrio.read_dataframe(acquired.path)
    if data.crs is None or data.crs.to_epsg() != 4326:
        raise PipelineError(f"dataset {dataset.name}: placeholder files must be GeoJSON in EPSG:4326")
    read = len(data)
    data = select_area(data, context.profile.area(dataset.area), dataset.select)
    records = []
    for row in data.to_dict("records"):
        identifier = text(row.get("id"))
        name = text(row.get("name")) or ""
        if identifier is None or not name.startswith(LABEL) or not bool(row.get("placeholder")):
            raise PipelineError(
                f"dataset {dataset.name}: feature {identifier!r} is not labelled as a placeholder (its "
                "name must "
                f"start with {LABEL!r} and it must have placeholder = true)",
                extensions={"dataset": dataset.name, "feature": identifier},
            )
        properties: dict[str, Any] = {
            key: value for key, value in row.items() if key not in ("id", "geometry") and value is not None
        }
        properties.update(dataset.properties)
        records.append((f"{dataset.id_prefix}{identifier}", clean(properties), row["geometry"]))
    return Extracted(
        frame=frame(records),
        operation=choose_operation("EPSG:4326"),
        transformation=(
            f"copied from {acquired.path.name}: development placeholders (not real data), constructed in "
            "EPSG:4326; "
            "coordinates rounded to 1e-7 degrees"
        ),
        source_crs="EPSG:4326",
        read_count=read,
        verification={"points": 0, "note": "constructed in EPSG:4326"},
    )
