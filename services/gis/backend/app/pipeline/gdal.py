"""GDAL command-line tools (``ogr2ogr``, ``ogrinfo``) as typed functions.

Commands are run as argument lists (never through a shell), with a timeout, and their failures are
raised with GDAL's own message. Coordinate operations are passed explicitly (``-ct``) when the pipeline
chose one, so that GDAL applies exactly the operation that is recorded in the lineage.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

from app.pipeline.errors import PipelineError

logger = logging.getLogger(__name__)

MIN_GDAL_VERSION: Final = (3, 8)  # PMTiles writing and ogrinfo -json
DEFAULT_TIMEOUT_S: Final = 3_600
_VERSION = re.compile(r"GDAL (\d+)\.(\d+)\.(\d+)")


class GdalError(PipelineError):
    code = "gdal_failed"
    title = "A GDAL command failed"


@dataclass(frozen=True, slots=True)
class LayerInfo:
    name: str
    feature_count: int | None
    geometry_type: str | None
    crs_wkt: str | None
    extent: tuple[float, float, float, float] | None
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    driver: str
    layers: tuple[LayerInfo, ...]

    def layer(self, name: str | None) -> LayerInfo:
        if name is None:
            if len(self.layers) != 1:
                raise GdalError(
                    f"the source has {len(self.layers)} layers "
                    f"({', '.join(layer.name for layer in self.layers)}); "
                    "name the one to use",
                    extensions={"layers": [layer.name for layer in self.layers]},
                )
            return self.layers[0]
        for layer in self.layers:
            if layer.name == name:
                return layer
        raise GdalError(
            f"the source has no layer {name!r}", extensions={"layers": [layer.name for layer in self.layers]}
        )


def _executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise GdalError(
            f"{name} is not installed; install GDAL >= {'.'.join(map(str, MIN_GDAL_VERSION))} (gdal-bin) "
            "or use "
            "the pipeline Docker image"
        )
    return path


def run(tool: str, arguments: Sequence[str], *, timeout_s: int = DEFAULT_TIMEOUT_S) -> str:
    command = [_executable(tool), *arguments]
    logger.info("running %s", tool, extra={"arguments": list(arguments)})
    try:
        completed = subprocess.run(  # noqa: S603 - argument list, no shell; the executable is resolved above
            command, capture_output=True, text=True, timeout=timeout_s, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise GdalError(f"{tool} did not finish within {timeout_s} s") from exc
    warnings = [line for line in completed.stderr.splitlines() if line.startswith("Warning")]
    if warnings:
        logger.warning(
            "%s reported %d warnings", tool, len(warnings), extra={"tool": tool, "warnings": warnings[:20]}
        )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip().splitlines()
        raise GdalError(
            f"{tool} failed: {message[-1] if message else f'exit code {completed.returncode}'}",
            extensions={"tool": tool, "stderr": completed.stderr[-4000:]},
        )
    return completed.stdout


@cache
def version() -> tuple[int, int, int]:
    output = run("ogrinfo", ["--version"])
    match = _VERSION.search(output)
    if match is None:
        raise GdalError(f"cannot read the GDAL version from {output!r}")
    found = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if found[:2] < MIN_GDAL_VERSION:
        raise GdalError(
            f"GDAL {'.'.join(map(str, found))} is too old; {'.'.join(map(str, MIN_GDAL_VERSION))} or later "
            "is needed"
        )
    return found


def version_string() -> str:
    return ".".join(map(str, version()))


def info(source: str | Path, *, open_options: Mapping[str, str] | None = None) -> DatasetInfo:
    """Layers, feature counts, geometry types, CRS and extents of a vector dataset (``ogrinfo -json``)."""
    arguments = ["-json", "-so", "-al", "-ro"]
    for key, value in (open_options or {}).items():
        arguments += ["-oo", f"{key}={value}"]
    document: dict[str, Any] = json.loads(run("ogrinfo", [*arguments, str(source)]))
    layers = []
    for layer in document.get("layers", []):
        geometry = (layer.get("geometryFields") or [{}])[0]
        crs = geometry.get("coordinateSystem") or {}
        extent = geometry.get("extent")
        layers.append(
            LayerInfo(
                name=layer["name"],
                feature_count=layer.get("featureCount"),
                geometry_type=geometry.get("type"),
                crs_wkt=crs.get("wkt"),
                extent=tuple(float(value) for value in extent) if extent and len(extent) == 4 else None,  # type: ignore[arg-type]
                fields=tuple(field["name"] for field in layer.get("fields", [])),
            )
        )
    return DatasetInfo(driver=document.get("driverShortName", ""), layers=tuple(layers))


@dataclass(frozen=True, slots=True)
class Translate:
    """One ``ogr2ogr`` run: a source (and layer) to a GeoPackage layer in EPSG:4326."""

    source: str
    destination: Path
    destination_layer: str
    source_layers: Sequence[str] = ()
    source_crs: str | None = None
    coordinate_operation: str | None = None
    target_crs: str = "EPSG:4326"
    spatial_filter: tuple[float, float, float, float] | None = None
    where: str | None = None
    select: Sequence[str] = ()
    open_options: Mapping[str, str] | None = None
    config: Mapping[str, str] | None = None
    promote_to_multi: bool = False
    append: bool = False

    def arguments(self) -> list[str]:
        arguments = [
            "-f",
            "GPKG",
            "-overwrite" if not self.append else "-append",
            "-update" if self.append else "",
        ]
        arguments = [value for value in arguments if value]
        for key, value in (self.config or {}).items():
            arguments += ["--config", key, value]
        for key, value in (self.open_options or {}).items():
            arguments += ["-oo", f"{key}={value}"]
        arguments += ["-t_srs", self.target_crs, "-dim", "XY", "-lco", "GEOMETRY_NAME=geom"]
        if self.source_crs is not None:
            arguments += ["-s_srs", self.source_crs]
        if self.coordinate_operation is not None:
            arguments += ["-ct", self.coordinate_operation]
        if self.spatial_filter is not None:
            arguments += ["-spat", *(repr(value) for value in self.spatial_filter), "-spat_srs", "EPSG:4326"]
        if self.where is not None:
            arguments += ["-where", self.where]
        if self.select:
            arguments += ["-select", ",".join(self.select)]
        if self.promote_to_multi:
            arguments += ["-nlt", "PROMOTE_TO_MULTI"]
        arguments += ["-nln", self.destination_layer, str(self.destination), self.source, *self.source_layers]
        return arguments


def translate(job: Translate, *, timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
    job.destination.parent.mkdir(parents=True, exist_ok=True)
    run("ogr2ogr", job.arguments(), timeout_s=timeout_s)


def write_pmtiles(
    source: Path,
    destination: Path,
    *,
    layer_config: Mapping[str, Any],
    min_zoom: int,
    max_zoom: int,
    name: str,
    description: str,
    simplification: float = 2.0,
    simplification_max_zoom: float = 0.5,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> None:
    """Vector tiles (MVT in a PMTiles archive, EPSG:3857) from the layers of a GeoPackage."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    arguments = [
        "-f",
        "PMTiles",
        "-dsco",
        f"MINZOOM={min_zoom}",
        "-dsco",
        f"MAXZOOM={max_zoom}",
        "-dsco",
        f"NAME={name}",
        "-dsco",
        f"DESCRIPTION={description}",
        "-dsco",
        "TYPE=baselayer",
        "-dsco",
        f"SIMPLIFICATION={simplification}",
        "-dsco",
        f"SIMPLIFICATION_MAX_ZOOM={simplification_max_zoom}",
        "-dsco",
        f"CONF={json.dumps(layer_config, separators=(',', ':'))}",
        str(destination),
        str(source),
    ]
    run("ogr2ogr", arguments, timeout_s=timeout_s)
