"""Source adapters: turn one source file into the features of one dataset.

Every adapter returns an :class:`Extracted`: a GeoDataFrame in EPSG:4326 with one row per feature
(``id``: the stable source identifier, ``properties``: the layer's columns plus source attributes,
``geometry``), the coordinate operation that produced it, a description of what was done, and notes
about features it left out and why. Adapters do not repair geometry and do not judge quality; the file
QA (:mod:`app.pipeline.file_qa`) and the database do.

* ``vector``: any file GDAL reads (Shapefile, GeoPackage, FileGDB, GeoJSON, CSV with WKT, ...), mapped to
  the layer's columns by a declared field mapping - the adapter for agency data.
* ``osm``: an OpenStreetMap extract (PBF), staged once with GDAL's OSM driver and classified by tag rules.
* ``placeholder``: labelled development placeholders (committed GeoJSON), refused in production.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.pipeline.crs import CoordinateOperation

if TYPE_CHECKING:
    import geopandas as gpd

    from app.pipeline.acquire import AcquiredSource
    from app.pipeline.profile import DatasetConfig, Profile, SourceConfig


@dataclass(frozen=True, slots=True)
class Note:
    """Something an adapter did to a feature, reported in the file QA report (info)."""

    check: str
    message: str
    source_feature_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Extracted:
    frame: gpd.GeoDataFrame
    operation: CoordinateOperation
    transformation: str
    source_crs: str
    read_count: int
    verification: dict[str, Any] = field(default_factory=dict)
    notes: list[Note] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BuildContext:
    profile: Profile
    raw_dir: Path
    staging_dir: Path


Adapter = Callable[["BuildContext", "DatasetConfig", "SourceConfig", "AcquiredSource"], Extracted]


def adapter_for(name: str) -> Adapter:
    from app.pipeline.adapters import osm, placeholder, vector

    adapters: dict[str, Adapter] = {
        "vector": vector.extract,
        "osm": osm.extract,
        "placeholder": placeholder.extract,
    }
    return adapters[name]
