"""Deterministic GeoJSON output: the same features always give the same bytes (and checksum).

Features are sorted by id, properties by name, coordinates rounded to 1e-7 degrees (about 1 cm, RFC 7946
recommends no more than needed), one feature per line, and gzip is written without a timestamp. The
checksum the pipeline and the loader record is that of the GeoJSON content (before compression).
"""

from __future__ import annotations

import datetime as dt
import decimal
import gzip
import hashlib
import io
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

PRECISION: Final = 7


def round_geometry(geometry: BaseGeometry) -> BaseGeometry:
    return shapely.transform(geometry, lambda coordinates: np.round(coordinates, PRECISION))


def plain(value: Any) -> Any:
    """JSON-ready Python values from numpy, pandas and datetime values."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    return value


def geojson_mapping(geometry: BaseGeometry) -> dict[str, Any]:
    return plain(mapping(round_geometry(geometry)))  # type: ignore[no-any-return]


def feature_collection(frame: gpd.GeoDataFrame) -> bytes:
    rows = sorted(
        zip(frame["id"], frame["properties"], frame.geometry, strict=True), key=lambda row: str(row[0])
    )
    lines = []
    for identifier, properties, geometry in rows:
        feature = {
            "type": "Feature",
            "id": str(identifier),
            "properties": {
                key: plain(properties[key]) for key in sorted(properties) if properties[key] is not None
            },
            "geometry": geojson_mapping(geometry),
        }
        lines.append(json.dumps(feature, ensure_ascii=False, separators=(",", ":"), sort_keys=False))
    body = ",\n".join(lines)
    return ('{"type":"FeatureCollection","features":[\n' + body + ("\n" if lines else "") + "]}\n").encode(
        "utf-8"
    )


def write(path: Path, content: bytes) -> str:
    """Write GeoJSON (gzip when the name ends in .gz) and return the SHA-256 of the GeoJSON content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as stream:
            stream.write(content)
        path.write_bytes(buffer.getvalue())
    else:
        path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()
