"""Helpers shared by the adapters: feature frames, area selection, value parsing."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry.base import BaseGeometry

from app.pipeline.profile import BBox

WGS84 = "EPSG:4326"
METRIC = "EPSG:5235"
_INTEGER = re.compile(r"^\s*(\d[\d,\s]*)\s*$")
_YEAR = re.compile(r"(1[89]\d\d|2[01]\d\d)")
_LATIN_LABEL = re.compile(r"^[\x20-\x7E\u00A0-\u024F\u2018-\u201F]+$")


def frame(records: Iterable[tuple[str | None, Mapping[str, Any], BaseGeometry]]) -> gpd.GeoDataFrame:
    rows = list(records)
    return gpd.GeoDataFrame(
        {
            "id": [row[0] for row in rows],
            "properties": [dict(row[1]) for row in rows],
        },
        geometry=[row[2] for row in rows],
        crs=WGS84,
    )


def empty_frame() -> gpd.GeoDataFrame:
    return frame([])


def select_area(data: gpd.GeoDataFrame, area: BBox, how: str) -> gpd.GeoDataFrame:
    """Keep features intersecting the box, or whose representative point lies in it."""
    if data.empty:
        return data
    box = shapely.box(*area)
    if how == "representative_point":
        points = data.geometry.representative_point()
        return data[points.within(box)]
    return data[data.geometry.intersects(box)]


def text(value: Any) -> str | None:
    """A non-blank string, or None (pandas NaN and empty strings included)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if value is pd.NA:
        return None
    result = str(value).strip()
    return result or None


def integer(value: Any) -> int | None:
    """``12,500`` -> 12500; anything that is not a plain non-negative integer -> None."""
    raw = text(value)
    if raw is None:
        return None
    match = _INTEGER.match(raw)
    if match is None:
        return None
    return int(re.sub(r"[,\s]", "", match.group(1)))


def year(value: Any) -> int | None:
    raw = text(value)
    if raw is None:
        return None
    match = _YEAR.search(raw)
    return int(match.group(1)) if match else None


def latin_label(*candidates: Any) -> str | None:
    """The first candidate written in Latin script (basemap labels: the glyphs are Latin-only)."""
    for candidate in candidates:
        value = text(candidate)
        if value is not None and _LATIN_LABEL.match(value):
            return value
    return None


def metric_area(geometry: gpd.GeoSeries) -> pd.Series:
    return geometry.to_crs(METRIC).area


def clean(properties: Mapping[str, Any]) -> dict[str, Any]:
    """Drop empty values so that the GeoJSON carries only what the source said."""
    return {key: value for key, value in properties.items() if value is not None and value != ""}
