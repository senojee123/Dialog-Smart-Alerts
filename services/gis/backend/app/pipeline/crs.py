"""Source CRS resolution and coordinate operations (pyproj), applied by GDAL and verified.

Rules (plan §5.2, risk R4):

* A source's CRS is **never guessed**. If the file states one and the profile declares one, they must be
  the same CRS; if the file states none, the profile must declare it; if neither, the build stops.
* The operation from the source CRS to EPSG:4326 is chosen by pyproj (the most accurate operation whose
  grids are available; "ballpark" operations are refused), or pinned in the profile. Its PROJ pipeline,
  description and published accuracy are recorded in the lineage and passed to ``ogr2ogr -ct``, so GDAL
  applies exactly the recorded operation.
* The result is **verified**: sample points are transformed by ``ogr2ogr`` and by pyproj and must agree,
  and surveyed control points given in the profile must land within their tolerance.

Sri Lankan CRSs met in practice: EPSG:5235 SLD99 / Sri Lanka Grid 1999 (current national grid; to WGS 84
with a published accuracy of 14 m), EPSG:5234 Kandawala / Sri Lanka Grid (legacy; 35 m), EPSG:32644 UTM
44N (WGS 84 based; a conversion, no datum change) and WGS 84 / CRS84 (GeoJSON, OpenStreetMap).
"""

from __future__ import annotations

import json
import math
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyproj
from pyproj.transformer import Transformer, TransformerGroup

from app.pipeline import gdal
from app.pipeline.errors import CrsError
from app.schemas.reference_data import WGS84_CRS

TARGET_CRS: Final = "EPSG:4326"
VERIFY_TOLERANCE_DEG: Final = 1e-7  # about 1 cm
_GEOD: Final = pyproj.Geod(ellps="WGS84")


@dataclass(frozen=True, slots=True)
class ControlPoint:
    name: str
    source: tuple[float, float]
    wgs84: tuple[float, float]
    tolerance_m: float


@dataclass(frozen=True, slots=True)
class CoordinateOperation:
    source_crs: str
    description: str
    pipeline: str | None
    accuracy_m: float | None
    proj_version: str

    @property
    def is_identity(self) -> bool:
        return self.pipeline is None

    def lineage(self) -> str:
        """Text recorded in ``meta.dataset_load.coordinate_operation``."""
        if self.pipeline is None:
            return f"none: {self.source_crs} coordinates are WGS 84 longitude/latitude"
        accuracy = "unknown accuracy" if self.accuracy_m is None else f"accuracy {self.accuracy_m:g} m"
        return f"{self.description} ({accuracy}; PROJ {self.proj_version}): +{self.pipeline}"

    def transformer_xy(self) -> Transformer:
        return Transformer.from_crs(self.source_crs, TARGET_CRS, always_xy=True)


def identifier(crs: pyproj.CRS) -> str | None:
    """``EPSG:nnnn`` (or ``OGC:CRS84``) for a CRS, if it has one with confidence."""
    if crs.equals(pyproj.CRS("OGC:CRS84")):
        return "OGC:CRS84"
    authority = crs.to_authority(min_confidence=70)
    if authority is None:
        return None
    name, code = authority
    return f"{name}:{code}" if name == "EPSG" else None


def resolve_source_crs(declared: str | None, detected_wkt: str | None, *, label: str) -> str:
    """The source CRS as ``EPSG:nnnn``: the file's, the profile's, and never a guess."""
    detected = pyproj.CRS.from_wkt(detected_wkt) if detected_wkt else None
    if declared is None and detected is None:
        raise CrsError(
            f"{label}: the file does not state its CRS and the profile does not declare one (source_crs); "
            "the pipeline does not guess coordinate systems",
            extensions={"source": label},
        )
    if declared is not None:
        try:
            declared_crs = pyproj.CRS(declared)
        except pyproj.exceptions.CRSError as exc:
            raise CrsError(f"{label}: unknown CRS {declared!r}", extensions={"source": label}) from exc
        if detected is not None and not declared_crs.equals(detected, ignore_axis_order=True):
            raise CrsError(
                f"{label}: the profile declares {declared} but the file is in {detected.name!r} "
                f"({identifier(detected) or 'no EPSG code'})",
                extensions={"source": label, "declared": declared, "detected": detected.name},
            )
        result = identifier(declared_crs)
    else:
        assert detected is not None
        result = identifier(detected)
        if result is None:
            raise CrsError(
                f"{label}: the file's CRS {detected.name!r} has no EPSG code; declare the equivalent EPSG "
                "code in "
                "the profile (source_crs) after checking it",
                extensions={"source": label, "detected": detected.name},
            )
    if result is None:
        raise CrsError(f"{label}: {declared!r} has no EPSG code", extensions={"source": label})
    return result


def choose_operation(
    source_crs: str, *, pinned: str | None = None, allow_ballpark: bool = False, label: str = ""
) -> CoordinateOperation:
    """The operation from ``source_crs`` to EPSG:4326, in authority axis order (what ``ogr2ogr -ct`` "
    "needs)."""
    proj_version = str(pyproj.proj_version_str)
    if source_crs in WGS84_CRS:
        return CoordinateOperation(source_crs, "none", None, 0.0, proj_version)
    if pinned is not None and pinned.lstrip("+").startswith("proj=pipeline"):
        return CoordinateOperation(source_crs, "pinned PROJ pipeline", pinned.lstrip("+"), None, proj_version)
    group = TransformerGroup(source_crs, TARGET_CRS, always_xy=False)
    candidates = list(group.transformers)
    if pinned is not None:
        candidates = [item for item in candidates if pinned.lower() in item.description.lower()]
        if not candidates:
            raise CrsError(
                f"{label}: no available operation from {source_crs} to {TARGET_CRS} matches {pinned!r}",
                extensions={"operations": [item.description for item in group.transformers]},
            )
    elif not group.best_available:
        raise CrsError(
            f"{label}: the most accurate operation from {source_crs} to {TARGET_CRS} needs PROJ grids that "
            "are "
            "not installed; install them (projsync) or pin an operation in the profile",
            extensions={"unavailable": [str(item) for item in group.unavailable_operations][:5]},
        )
    if not candidates:
        raise CrsError(f"{label}: no operation from {source_crs} to {TARGET_CRS}")
    chosen = candidates[0]
    if "ballpark" in chosen.description.lower() and not allow_ballpark:
        raise CrsError(
            f"{label}: only a ballpark operation ({chosen.description}) is available from {source_crs}; its "
            "error can reach hundreds of metres",
            extensions={"operation": chosen.description},
        )
    accuracy = chosen.accuracy if chosen.accuracy is not None and chosen.accuracy >= 0 else None
    return CoordinateOperation(
        source_crs=source_crs,
        description=chosen.description,
        pipeline=chosen.definition,
        accuracy_m=accuracy,
        proj_version=proj_version,
    )


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    _, _, distance = _GEOD.inv(a[0], a[1], b[0], b[1])
    return float(distance)


def verify_operation(
    operation: CoordinateOperation,
    sample: Sequence[tuple[float, float]],
    *,
    control_points: Sequence[ControlPoint] = (),
    label: str = "",
) -> dict[str, float | int]:
    """Transform sample and control points with ``ogr2ogr`` (as the pipeline does) and with pyproj.

    GDAL and pyproj must agree to about a centimetre (a wrong axis order or pipeline shows up as
    kilometres); control points must land within their tolerance of their surveyed WGS 84 position.
    """
    points = [*sample, *(point.source for point in control_points)]
    if operation.is_identity or not points:
        return {"points": 0, "maxDeviationDeg": 0.0, "controlPoints": 0}
    by_gdal = _transform_with_gdal(operation, points)
    by_proj = [operation.transformer_xy().transform(x, y) for x, y in points]
    deviation = max(max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(by_gdal, by_proj, strict=True))
    if deviation > VERIFY_TOLERANCE_DEG or not all(math.isfinite(v) for p in by_gdal for v in p):
        raise CrsError(
            f"{label}: ogr2ogr and pyproj disagree by {deviation:.3g} degrees applying "
            f"{operation.description}; "
            "check the axis order and the pipeline",
            extensions={"deviationDeg": deviation},
        )
    worst = 0.0
    for point, landed in zip(control_points, by_gdal[len(sample) :], strict=True):
        error = distance_m(landed, point.wgs84)
        worst = max(worst, error)
        if error > point.tolerance_m:
            raise CrsError(
                f"{label}: control point {point.name} lands {error:.2f} m from its surveyed position "
                f"(tolerance {point.tolerance_m:g} m) with {operation.description}",
                extensions={"controlPoint": point.name, "errorM": round(error, 3)},
            )
    return {
        "points": len(points),
        "maxDeviationDeg": deviation,
        "controlPoints": len(control_points),
        "controlPointMaxErrorM": round(worst, 3),
    }


def _transform_with_gdal(
    operation: CoordinateOperation, points: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    with tempfile.TemporaryDirectory(prefix="gis-crs-") as directory:
        source = Path(directory) / "points.geojson"
        target = Path(directory) / "points.gpkg"
        source.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": index,
                            "properties": {},
                            "geometry": {"type": "Point", "coordinates": [x, y]},
                        }
                        for index, (x, y) in enumerate(points)
                    ],
                }
            ),
            encoding="utf-8",
        )
        gdal.translate(
            gdal.Translate(
                source=str(source),
                destination=target,
                destination_layer="points",
                source_crs=operation.source_crs,
                coordinate_operation=None if operation.pipeline is None else f"+{operation.pipeline}",
            )
        )
        import pyogrio  # the pipeline's own dependency; imported here to keep this module light

        frame = pyogrio.read_dataframe(target, layer="points")
        return [(float(geometry.x), float(geometry.y)) for geometry in frame.geometry]
