"""The reference data manifest: what the pipeline hands to the loader, and what the loader records.

A manifest (``manifest.json``) describes one reference data release: its code and purpose, the data
sources with their licences, and the GIS-ready GeoJSON files to load, each with its lineage (where the
original came from, which version, when it was retrieved, its CRS and the coordinate operation applied,
its accuracy), the expectations the QA checks hold it to, and the report of the checks already run on the
file by the pipeline. Nothing about licensing is assumed: every source states its licence, whether it
permits commercial use and redistribution, and whether it has been reviewed.

The models are shared by the loader (``app.services.reference_loader``), the database QA
(``app.services.reference_qa``) and the pipeline (``app.pipeline``), so the three agree on one format.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic.alias_generators import to_camel

from app.core.errors import GisError

RELEASE_CODE_PATTERN: Final = r"^ref-[0-9]{4}\.[0-9]{2}(-[a-z0-9]+)*$"
SOURCE_CODE_PATTERN: Final = r"^[a-z0-9][a-z0-9_.-]{1,62}$"
CRS_PATTERN: Final = r"^(EPSG:[0-9]{4,6}|OGC:CRS84)$"
SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
CHECK_CODE_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
STORAGE_CRS: Final = "EPSG:4326"
# The source CRSs whose coordinates are stored as they are (longitude, latitude on WGS 84).
WGS84_CRS: Final = frozenset({"EPSG:4326", "OGC:CRS84"})

ReleasePurpose = Literal["production", "development", "test"]
ReviewStatus = Literal["unreviewed", "approved", "rejected"]
Severity = Literal["error", "warning", "info"]
QaStatus = Literal["passed", "warnings", "failed"]
ReferenceLayerCode = Literal[
    "ref.admin_area",
    "ref.settlement",
    "ref.facility",
    "ref.road",
    "ref.water_body",
    "ref.protected_area",
    "ref.risk_zone",
]


def merge_attribution(statements: Iterable[str]) -> list[str]:
    """Attribution statements without repeats: one contained in another is left out, order kept.

    ``© OpenStreetMap contributors`` adds nothing next to ``© OpenStreetMap contributors (ODbL); ...``.
    """
    unique = list(dict.fromkeys(item.strip() for item in statements if item.strip()))
    return [item for item in unique if not any(item != other and item in other for other in unique)]


class ReferenceDataError(GisError):
    status_code = 422
    code = "reference_load_failed"
    title = "Reference data could not be loaded"


class ManifestModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid")


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonBlank = Annotated[str, AfterValidator(_not_blank)]


class LicenceReview(ManifestModel):
    """A decision about whether a source's licence permits the intended deployment."""

    status: ReviewStatus
    reviewed_by: NonBlank | None = None
    reviewed_on: date | None = None
    reference: NonBlank | None = Field(
        default=None, description="Legal memo, ticket or agreement the decision refers to."
    )

    @model_validator(mode="after")
    def _decision_is_recorded(self) -> LicenceReview:
        if self.status != "unreviewed" and None in (self.reviewed_by, self.reviewed_on, self.reference):
            raise ValueError(
                f"a licence review that is {self.status} needs reviewedBy, reviewedOn and reference"
            )
        return self


class SourceSpec(ManifestModel):
    code: str = Field(pattern=SOURCE_CODE_PATTERN)
    name: NonBlank
    publisher: NonBlank
    url: str | None = None
    licence: NonBlank = Field(description="Licence identifier, SPDX where one exists.")
    licence_url: str | None = None
    attribution: NonBlank
    commercial_use_allowed: bool
    redistribution_allowed: bool
    share_alike: bool = False
    permission_reference: str | None = None
    licence_review: LicenceReview = LicenceReview(status="unreviewed")
    notes: str | None = None

    @model_validator(mode="after")
    def _commercial_use_is_permitted(self) -> SourceSpec:
        if not self.commercial_use_allowed and not self.permission_reference:
            raise ValueError(
                f"source {self.code}: the licence does not permit commercial use; record the written "
                "permission in permissionReference or leave the source out"
            )
        return self


class QaExpectations(ManifestModel):
    """What the QA checks hold a dataset to. Unset values fall back to the layer's defaults."""

    expected_bbox: tuple[float, float, float, float] | None = Field(
        default=None, description="Features must lie within this WGS84 box (minLon, minLat, maxLon, maxLat)."
    )
    extent_tolerance_m: float = Field(default=1_000.0, ge=0)
    min_coverage_ratio: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="The dataset's extent must span at least this share of the expected box in both "
        "directions (catches a national dataset that only covers one district).",
    )
    min_features: int | None = Field(default=None, ge=0)
    max_features: int | None = Field(default=None, ge=0)
    max_count_change_ratio: float = Field(default=0.5, ge=0)
    max_rejected_ratio: float = Field(default=0.01, ge=0, le=1)
    min_area_m2: float | None = Field(default=None, ge=0)
    max_area_m2: float | None = Field(default=None, gt=0)
    min_length_m: float = Field(default=1.0, ge=0)
    max_segment_m: float | None = Field(default=None, gt=0)
    max_vertices: int = Field(default=100_000, gt=0)
    duplicate_distance_m: float | None = Field(default=None, gt=0)
    overlap_tolerance_m2: float = Field(default=10_000.0, ge=0)
    overlap_error_ratio: float = Field(default=0.05, gt=0, le=1)
    containment_warn_ratio: float = Field(default=0.98, gt=0, le=1)
    containment_error_ratio: float = Field(default=0.5, gt=0, le=1)
    gap_tolerance_ratio: float = Field(default=0.01, ge=0, le=1)
    coast_buffer_m: float = Field(default=2_000.0, ge=0)
    repair_area_warn_ratio: float = Field(
        default=0.001, ge=0, description="A repair that changed the area by more than this share warns."
    )
    repair_shift_warn_m: float = Field(
        default=1.0, ge=0, description="A repair that moved the boundary by more than this warns."
    )
    repair_shift_error_m: float = Field(
        default=100.0, ge=0, description="A repair that moved the boundary by more than this is an error."
    )
    code_pattern: str | None = Field(default=None, description="Regular expression admin codes must match.")

    @model_validator(mode="after")
    def _consistent(self) -> QaExpectations:
        if self.expected_bbox is not None:
            min_lon, min_lat, max_lon, max_lat = self.expected_bbox
            if not (min_lon < max_lon and min_lat < max_lat):
                raise ValueError("expectedBbox must be minLon, minLat, maxLon, maxLat with min < max")
        if (
            self.min_features is not None
            and self.max_features is not None
            and self.min_features > self.max_features
        ):
            raise ValueError("minFeatures is larger than maxFeatures")
        if self.containment_error_ratio > self.containment_warn_ratio:
            raise ValueError("containmentErrorRatio must not exceed containmentWarnRatio")
        if self.repair_shift_warn_m > self.repair_shift_error_m:
            raise ValueError("repairShiftWarnM must not exceed repairShiftErrorM")
        return self


class FileQaFinding(ManifestModel):
    check: str = Field(pattern=CHECK_CODE_PATTERN)
    severity: Severity
    message: NonBlank
    source_feature_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    location: dict[str, Any] | None = Field(default=None, description="GeoJSON geometry (WGS84).")


class FileQaReport(ManifestModel):
    """What the pipeline's checks found in one output file (stored as a QA run of stage ``file``)."""

    file: NonBlank
    sha256: str = Field(pattern=SHA256_PATTERN, description="SHA-256 of the GeoJSON content checked.")
    status: QaStatus
    checks: list[str]
    counts: dict[str, int] = Field(default_factory=dict)
    findings: list[FileQaFinding] = Field(default_factory=list)
    finding_count: int = Field(default=0, ge=0, description="Findings before truncation.")
    parameters: dict[str, Any] = Field(default_factory=dict)
    tool_version: NonBlank
    checked_at: datetime

    @model_validator(mode="after")
    def _aware(self) -> FileQaReport:
        if self.checked_at.tzinfo is None:
            raise ValueError("checkedAt needs a UTC offset")
        return self


class FileSpec(ManifestModel):
    path: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.geojson(\.gz)?$")
    layer: ReferenceLayerCode
    source: str = Field(pattern=SOURCE_CODE_PATTERN)
    source_reference: NonBlank = Field(description="URL or reference of the exact file or delivery.")
    source_version: NonBlank
    source_retrieved_at: datetime | None = None
    original_file: str | None = None
    original_checksum_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    source_crs: str = Field(default=STORAGE_CRS, pattern=CRS_PATTERN)
    coordinate_operation: str | None = None
    transformation: NonBlank
    geometry_source: str = "unknown"
    geometry_accuracy_m: float = Field(gt=0)
    properties: dict[str, Any] = Field(default_factory=dict, description="Column values for every feature.")
    parent_by: Literal["code", "location"] | None = None
    admin_area_by: Literal["location"] | None = None
    qa: QaExpectations = QaExpectations()
    qa_report: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.json$", description="File QA report (JSON)."
    )
    tool_versions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _lineage_is_complete(self) -> FileSpec:
        if self.source_crs not in WGS84_CRS and not self.coordinate_operation:
            raise ValueError(
                f"{self.path}: the source CRS is {self.source_crs}; record the coordinate operation used "
                "to reach EPSG:4326 (coordinateOperation)"
            )
        if self.source_retrieved_at is not None and self.source_retrieved_at.tzinfo is None:
            raise ValueError(f"{self.path}: sourceRetrievedAt needs a UTC offset")
        return self


class ReleaseSpec(ManifestModel):
    code: str = Field(pattern=RELEASE_CODE_PATTERN)
    purpose: ReleasePurpose
    description: str | None = None


class Manifest(ManifestModel):
    release: ReleaseSpec
    sources: list[SourceSpec]
    files: list[FileSpec]

    @model_validator(mode="after")
    def _sources_are_declared(self) -> Manifest:
        codes = [source.code for source in self.sources]
        duplicates = sorted({code for code in codes if codes.count(code) > 1})
        if duplicates:
            raise ValueError(f"sources declared twice: {', '.join(duplicates)}")
        missing = sorted({spec.source for spec in self.files} - set(codes))
        if missing:
            raise ValueError(f"files refer to sources the manifest does not declare: {', '.join(missing)}")
        return self

    @classmethod
    def read(cls, path: Path) -> Manifest:
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ReferenceDataError(f"cannot read manifest {path}: {exc.strerror}") from exc
        except ValidationError as exc:
            raise ReferenceDataError(
                f"invalid manifest {path.name}", extensions={"errors": validation_problems(exc)}
            ) from exc


def validation_problems(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"location": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
