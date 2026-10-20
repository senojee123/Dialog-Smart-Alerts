"""File-level QA: what the pipeline checks in each dataset before it is written and loaded.

Runs on the features exactly as they will be written (coordinates already rounded), with GeoPandas and
Shapely:

* **CRS**: the output is EPSG:4326 and the operation used to get there was verified (see
  :mod:`app.pipeline.crs`);
* **per feature** (the feature is left out and the finding reported as a warning): empty geometry, a
  geometry type the layer does not hold, no identifier, a duplicate identifier (the first is kept), no
  name where the layer needs one, outside the service area (with "latitude and longitude swapped?" when
  swapping would put it inside), a polygon whose repair would leave nothing;
* **reported, not changed**: invalid polygons (``shapely.is_valid_reason``; the database repairs them on
  load and logs the original), identical geometries under different ids, too many vertices;
* **per dataset** (errors that fail the build): features outside the expected extent, a feature count
  outside the expected range, too many features left out, a dataset covering too little of its extent.

The adapters' own notes (features they skipped or merged, and why) are included as information.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import geopandas as gpd
import shapely

from app import __version__
from app.pipeline.adapters import Extracted
from app.pipeline.features import clean, text
from app.pipeline.writer import geojson_mapping, round_geometry
from app.schemas.reference_data import FileQaFinding, FileQaReport, QaExpectations, QaStatus, Severity
from app.services.reference_loader import LAYERS

MAX_FINDINGS_PER_CHECK: Final = 50
DEGREES_PER_METRE: Final = 1 / 111_320.0
NAME_REQUIRED: Final = frozenset(
    {"ref.admin_area", "ref.settlement", "ref.facility", "ref.protected_area", "ref.risk_zone"}
)
CHECKS: Final = (
    "crs.storage",
    "crs.operation",
    "geometry.empty",
    "geometry.type",
    "geometry.invalid",
    "geometry.unrepairable",
    "identifier.missing",
    "identifier.duplicate",
    "identifier.name_missing",
    "duplicate.geometry",
    "outlier.service_area",
    "outlier.extent",
    "outlier.coverage",
    "outlier.vertices",
    "outlier.count",
    "outlier.rejected",
    "transform.skipped",
    "transform.merged",
)


@dataclass(slots=True)
class FileQaResult:
    frame: gpd.GeoDataFrame
    status: QaStatus
    findings: list[FileQaFinding]
    finding_count: int
    counts: dict[str, int]
    parameters: dict[str, Any] = field(default_factory=dict)

    def report(self, file: str, sha256: str) -> FileQaReport:
        return FileQaReport(
            file=file,
            sha256=sha256,
            status=self.status,
            checks=list(CHECKS),
            counts=self.counts,
            findings=self.findings,
            finding_count=self.finding_count,
            parameters=self.parameters,
            tool_version=f"gis-core-service {__version__} pipeline",
            checked_at=datetime.now(UTC),
        )


class _Findings:
    def __init__(self) -> None:
        self.items: list[FileQaFinding] = []
        self.per_check: Counter[str] = Counter()
        self.severities: Counter[str] = Counter()

    def add(
        self,
        check: str,
        severity: Severity,
        message: str,
        *,
        feature: str | None = None,
        geometry: Any = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.per_check[check] += 1
        self.severities[severity] += 1
        if self.per_check[check] > MAX_FINDINGS_PER_CHECK:
            return
        location = None
        if geometry is not None and not geometry.is_empty:
            try:
                location = geojson_mapping(geometry.representative_point())
            except shapely.errors.GEOSException:
                location = None
        self.items.append(
            FileQaFinding(
                check=check,
                severity=severity,
                message=message,
                source_feature_id=feature,
                details=dict(details or {}),
                location=location,
            )
        )

    @property
    def total(self) -> int:
        return sum(self.per_check.values())


def _swapped_inside(geometry: Any, area: tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = geometry.bounds
    return bool(area[0] <= y0 and y1 <= area[2] and area[1] <= x0 and x1 <= area[3])


def check(
    extracted: Extracted,
    *,
    layer: str,
    expectations: QaExpectations,
    service_area: tuple[float, float, float, float],
) -> FileQaResult:
    findings = _Findings()
    data = extracted.frame
    if data.crs is None or data.crs.to_epsg() != 4326:
        findings.add("crs.storage", "error", f"the output is in {data.crs}, not EPSG:4326")
    findings.add(
        "crs.operation",
        "info",
        f"source CRS {extracted.source_crs}: {extracted.operation.lineage()}",
        details={key: value for key, value in extracted.verification.items() if value is not None},
    )
    for note in extracted.notes:
        findings.add(note.check, "info", note.message, feature=note.source_feature_id, details=note.details)

    allowed = LAYERS[layer].allowed_types
    x0, y0, x1, y1 = service_area
    kept_ids: list[str] = []
    kept_properties: list[dict[str, Any]] = []
    kept_geometries: list[Any] = []
    seen: dict[str, tuple[bytes, dict[str, Any]]] = {}
    geometry_owner: dict[bytes, str] = {}
    rejected = 0
    invalid = 0
    for identifier, properties, raw_geometry in zip(
        data["id"], data["properties"], data.geometry, strict=True
    ):
        # pandas keeps a missing identifier as NaN, which str() would turn into "nan".
        feature = text(identifier)
        properties = clean(properties or {})
        if raw_geometry is None or raw_geometry.is_empty:
            findings.add("geometry.empty", "warning", "empty geometry: left out", feature=feature)
            rejected += 1
            continue
        geometry = round_geometry(raw_geometry)
        if geometry.geom_type not in allowed:
            findings.add(
                "geometry.type",
                "warning",
                f"{geometry.geom_type} is not a geometry {layer} holds: left out",
                feature=feature,
                geometry=geometry,
            )
            rejected += 1
            continue
        if feature is None:
            findings.add("identifier.missing", "warning", "no identifier: left out", geometry=geometry)
            rejected += 1
            continue
        gx0, gy0, gx1, gy1 = geometry.bounds
        if not (x0 <= gx0 and gx1 <= x1 and y0 <= gy0 and gy1 <= y1):
            swapped = _swapped_inside(geometry, service_area)
            findings.add(
                "outlier.service_area",
                "warning",
                "outside the service area"
                + (" (latitude and longitude swapped?)" if swapped else "")
                + ": left out",
                feature=feature,
                details={"bounds": [gx0, gy0, gx1, gy1], "likelySwapped": swapped},
            )
            rejected += 1
            continue
        if layer in NAME_REQUIRED and not properties.get("name"):
            findings.add(
                "identifier.name_missing", "warning", "no name: left out", feature=feature, geometry=geometry
            )
            rejected += 1
            continue
        key = shapely.to_wkb(shapely.normalize(geometry), hex=False)
        if feature in seen:
            same = seen[feature] == (key, properties)
            findings.add(
                "identifier.duplicate",
                "warning" if not same else "info",
                (
                    "an exact copy of an earlier feature"
                    if same
                    else "the identifier is used by an earlier feature"
                )
                + ": left out",
                feature=feature,
                geometry=geometry,
            )
            rejected += 0 if same else 1
            continue
        seen[feature] = (key, properties)
        if geometry.geom_type in ("Polygon", "MultiPolygon") and not geometry.is_valid:
            repaired = shapely.make_valid(geometry, method="structure", keep_collapsed=False)
            polygonal = shapely.get_parts(repaired)
            area = sum(part.area for part in polygonal if part.geom_type in ("Polygon", "MultiPolygon"))
            if area <= 0:
                findings.add(
                    "geometry.unrepairable",
                    "warning",
                    f"invalid polygon that collapses when repaired ({shapely.is_valid_reason(geometry)}): "
                    "left out",
                    feature=feature,
                    geometry=geometry,
                )
                rejected += 1
                continue
            invalid += 1
            findings.add(
                "geometry.invalid",
                "warning",
                f"invalid polygon ({shapely.is_valid_reason(geometry)}); the database repairs it on load "
                "and logs "
                "the original",
                feature=feature,
                geometry=geometry,
                details={"reason": shapely.is_valid_reason(geometry)},
            )
        if key in geometry_owner:
            findings.add(
                "duplicate.geometry",
                "warning",
                f"the same geometry as {geometry_owner[key]}",
                feature=feature,
                geometry=geometry,
                details={"sameAs": geometry_owner[key]},
            )
        else:
            geometry_owner[key] = feature
        vertices = shapely.get_num_coordinates(geometry)
        if vertices > expectations.max_vertices:
            findings.add(
                "outlier.vertices",
                "warning",
                f"{vertices} vertices (more than {expectations.max_vertices})",
                feature=feature,
                geometry=geometry,
            )
        kept_ids.append(feature)
        kept_properties.append(properties)
        kept_geometries.append(geometry)

    kept = gpd.GeoDataFrame(
        {"id": kept_ids, "properties": kept_properties}, geometry=kept_geometries, crs=4326
    )
    extracted_count = len(data)
    if expectations.expected_bbox is not None and not kept.empty:
        pad = expectations.extent_tolerance_m * DEGREES_PER_METRE
        ex0, ey0, ex1, ey1 = expectations.expected_bbox
        box = shapely.box(ex0 - pad, ey0 - pad, ex1 + pad, ey1 + pad)
        outside = kept[~kept.geometry.covered_by(box)]
        for feature, geometry in zip(outside["id"], outside.geometry, strict=True):
            findings.add(
                "outlier.extent", "error", "outside the expected extent", feature=feature, geometry=geometry
            )
        if expectations.min_coverage_ratio is not None:
            bx0, by0, bx1, by1 = kept.total_bounds
            width = (bx1 - bx0) / (ex1 - ex0)
            height = (by1 - by0) / (ey1 - ey0)
            if min(width, height) < expectations.min_coverage_ratio:
                findings.add(
                    "outlier.coverage",
                    "warning",
                    f"spans {width:.0%} x {height:.0%} of the expected extent "
                    f"(at least {expectations.min_coverage_ratio:.0%} expected)",
                )
    count = len(kept)
    if expectations.min_features is not None and count < expectations.min_features:
        findings.add(
            "outlier.count", "error", f"{count} features, at least {expectations.min_features} expected"
        )
    if expectations.max_features is not None and count > expectations.max_features:
        findings.add(
            "outlier.count", "error", f"{count} features, at most {expectations.max_features} expected"
        )
    if rejected:
        share = rejected / extracted_count if extracted_count else 1.0
        findings.add(
            "outlier.rejected",
            "error" if share > expectations.max_rejected_ratio else "info",
            f"{rejected} of {extracted_count} features left out ({share:.2%}; at most "
            f"{expectations.max_rejected_ratio:.2%} allowed)",
            details={"rejected": rejected, "extracted": extracted_count},
        )
    by_check: dict[str, int] = defaultdict(int)
    for name, number in findings.per_check.items():
        by_check[name] = number
    status: QaStatus = (
        "failed"
        if findings.severities["error"]
        else ("warnings" if findings.severities["warning"] else "passed")
    )
    return FileQaResult(
        frame=kept,
        status=status,
        findings=findings.items,
        finding_count=findings.total,
        counts={
            "read": extracted.read_count,
            "extracted": extracted_count,
            "written": count,
            "leftOut": rejected,
            "invalidPolygons": invalid,
            "errors": findings.severities["error"],
            "warnings": findings.severities["warning"],
            "infos": findings.severities["info"],
        },
        parameters={
            "expectations": expectations.model_dump(mode="json", exclude_unset=True),
            "findingsPerCheck": dict(by_check),
        },
    )
