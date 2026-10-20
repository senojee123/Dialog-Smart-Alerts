"""Pipeline profiles: which sources, under which licences, become which datasets of a release.

A profile is a TOML file (``data/pipeline/profiles/*.toml``)::

    [profile]           name, purpose (production | development | test), release code template, description
    [areas]             named WGS84 boxes: national, pilot, ...
    [sources.<code>]    one per source: publisher, licence and review, where the file is (and where to
                        download it), checksum, version, declared CRS, pinned operation, control points
    [[datasets]]        one per output file: target layer, source, adapter (vector | osm | placeholder),
                        area, field mapping or OSM theme, constants, accuracy, QA expectations
    [basemap]           the vector tile basemap built with the release

Production profiles live with the deployment, not in the repository: ``--profile`` takes any path, source
locations may come from environment variables (``download_env``) and credentials only ever do
(``auth_header_env``).

Licensing is checked before anything is read (:func:`check_licences`): every source states its licence,
commercial use and redistribution; restricted licences (WDPA, non-commercial, no-derivatives) need a
recorded permission in every profile; a production profile needs an approved review for every source and
may not use placeholders.
"""

from __future__ import annotations

import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.models.common import GEOMETRY_SOURCES
from app.pipeline.crs import ControlPoint
from app.pipeline.errors import LicenceError, ProfileError
from app.schemas.reference_data import (
    CRS_PATTERN,
    RELEASE_CODE_PATTERN,
    SHA256_PATTERN,
    SOURCE_CODE_PATTERN,
    LicenceReview,
    QaExpectations,
    ReferenceLayerCode,
    ReleasePurpose,
    SourceSpec,
    validation_problems,
)
from app.services.reference_qa import RESTRICTED_LICENCE

DATASET_NAME_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{1,62}$"
OSM_THEMES: Final = ("settlements", "facilities", "roads", "water_lines", "water_areas", "protected_areas")
BBox = tuple[float, float, float, float]


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProfileSettings(_Config):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    purpose: ReleasePurpose
    release: str = Field(
        description="Release code or template with {year} and {month}, e.g. ref-{year}.{month}-dev."
    )
    description: str

    def release_code(self, now: datetime | None = None) -> str:
        moment = now or datetime.now(UTC)
        code = self.release.format(year=f"{moment.year:04d}", month=f"{moment.month:02d}")
        if not re.fullmatch(RELEASE_CODE_PATTERN, code):
            raise ProfileError(f"release code {code!r} does not match {RELEASE_CODE_PATTERN}")
        return code


class ControlPointConfig(_Config):
    name: str
    source: tuple[float, float] = Field(description="Coordinates in the source CRS.")
    wgs84: tuple[float, float] = Field(description="Surveyed WGS 84 longitude, latitude.")
    tolerance_m: float = Field(gt=0)

    def point(self) -> ControlPoint:
        return ControlPoint(self.name, self.source, self.wgs84, self.tolerance_m)


class SourceConfig(_Config):
    code: str = Field(pattern=SOURCE_CODE_PATTERN)
    name: str
    publisher: str
    url: str | None = Field(default=None, description="Home page of the source.")
    licence: str
    licence_url: str | None = None
    attribution: str
    commercial_use_allowed: bool
    redistribution_allowed: bool
    share_alike: bool = False
    permission_reference: str | None = None
    review: LicenceReview = LicenceReview(status="unreviewed")
    notes: str | None = None
    # Where the file is and where it comes from.
    file: str = Field(
        description="Path of the original file, relative to the raw data directory (or the profile)."
    )
    base: Literal["raw", "profile"] = Field(
        default="raw",
        description="Whether file is relative to the raw data directory or to the profile's directory.",
    )
    download: str | None = Field(default=None, description="https URL to download the file from.")
    download_env: str | None = Field(default=None, description="Environment variable holding that URL.")
    auth_header_env: str | None = Field(
        default=None, description="Environment variable holding an Authorization header for the download."
    )
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    version: str | None = None
    version_from: Literal["osm_replication_timestamp"] | None = None
    # Coordinates.
    source_crs: str | None = Field(default=None, pattern=CRS_PATTERN)
    coordinate_operation: str | None = Field(
        default=None, description="Pin an operation: part of its description, or a PROJ pipeline."
    )
    allow_ballpark: bool = False
    control_points: list[ControlPointConfig] = Field(default_factory=list)
    open_options: dict[str, str] = Field(default_factory=dict)
    geometry_source: str = "unknown"

    @field_validator("download")
    @classmethod
    def _https(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("downloads must use https")
        return value

    @field_validator("geometry_source")
    @classmethod
    def _geometry_source(cls, value: str) -> str:
        if value not in GEOMETRY_SOURCES:
            raise ValueError(f"must be one of {', '.join(GEOMETRY_SOURCES)}")
        return value

    @model_validator(mode="after")
    def _version_known(self) -> SourceConfig:
        if self.version is None and self.version_from is None:
            raise ValueError(f"source {self.code}: state its version (version or version_from)")
        return self

    def spec(self) -> SourceSpec:
        return SourceSpec(
            code=self.code,
            name=self.name,
            publisher=self.publisher,
            url=self.url,
            licence=self.licence,
            licence_url=self.licence_url,
            attribution=self.attribution,
            commercial_use_allowed=self.commercial_use_allowed,
            redistribution_allowed=self.redistribution_allowed,
            share_alike=self.share_alike,
            permission_reference=self.permission_reference,
            licence_review=self.review,
            notes=self.notes,
        )


class DatasetQa(QaExpectations):
    expected_area: str | None = Field(default=None, description="Name of an area: sets expected_bbox.")


class DatasetConfig(_Config):
    name: str = Field(pattern=DATASET_NAME_PATTERN, description="Output file name (without extension).")
    layer: ReferenceLayerCode
    source: str = Field(pattern=SOURCE_CODE_PATTERN)
    adapter: Literal["vector", "osm", "placeholder"]
    description: str | None = None
    area: str = "national"
    select: Literal["intersects", "representative_point"] = "intersects"
    # vector adapter
    input_layer: str | None = None
    where: str | None = Field(default=None, description="Attribute filter (ogr2ogr -where) on the source.")
    id_field: str | None = None
    fields: dict[str, str] = Field(default_factory=dict, description="Target column -> source field.")
    values: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="Target column -> {source value: target value}."
    )
    keep_attributes: list[str] = Field(default_factory=list, description="Source fields kept in attributes.")
    # osm adapter
    theme: (
        Literal["settlements", "facilities", "roads", "water_lines", "water_areas", "protected_areas"] | None
    ) = None
    classes: list[str] = Field(default_factory=list)
    min_area_m2: float | None = Field(default=None, ge=0)
    # every adapter
    id_prefix: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)
    parent_by: Literal["code", "location"] | None = None
    admin_area_by: Literal["location"] | None = None
    geometry_source: str | None = None
    accuracy_m: float = Field(gt=0, description="Nominal horizontal accuracy of the dataset in metres.")
    qa: DatasetQa = DatasetQa()

    @model_validator(mode="after")
    def _adapter_options(self) -> DatasetConfig:
        if self.adapter == "osm" and self.theme is None:
            raise ValueError(f"dataset {self.name}: the osm adapter needs a theme ({', '.join(OSM_THEMES)})")
        if self.adapter != "osm" and (self.theme is not None or self.classes):
            raise ValueError(f"dataset {self.name}: theme and classes apply to the osm adapter only")
        if self.adapter != "vector" and (self.fields or self.values or self.where or self.input_layer):
            raise ValueError(
                f"dataset {self.name}: fields, values, where and input_layer apply to the vector adapter"
            )
        if self.layer == "ref.admin_area" and not isinstance(self.properties.get("level"), int):
            raise ValueError(f"dataset {self.name}: admin areas need an integer properties.level")
        if self.geometry_source is not None and self.geometry_source not in GEOMETRY_SOURCES:
            raise ValueError(
                f"dataset {self.name}: geometry_source must be one of {', '.join(GEOMETRY_SOURCES)}"
            )
        return self


class BasemapConfig(_Config):
    name: str = Field(default="basemap", pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    osm_source: str = Field(pattern=SOURCE_CODE_PATTERN)
    land_source: str = Field(pattern=SOURCE_CODE_PATTERN, description="Country outline (polygon) source.")
    glyphs_source: str | None = Field(default=None, pattern=SOURCE_CODE_PATTERN)
    glyph_ranges: list[str] = Field(default_factory=lambda: ["0-255", "256-511", "8192-8447"])
    font: str = "Noto Sans Regular"
    min_zoom: int = Field(default=0, ge=0, le=16)
    max_zoom: int = Field(default=14, ge=0, le=16)
    detail_area: str = "pilot"
    public_path: str = Field(
        default="/basemap", description="URL path the web server serves the basemap directory under."
    )


class Profile(_Config):
    directory: Path | None = Field(default=None, exclude=True, description="Directory of the profile file.")
    profile: ProfileSettings
    areas: dict[str, tuple[float, float, float, float]]
    sources: dict[str, SourceConfig]
    datasets: list[DatasetConfig]
    basemap: BasemapConfig | None = None

    @model_validator(mode="after")
    def _references(self) -> Profile:
        problems: list[str] = []
        for name, (min_lon, min_lat, max_lon, max_lat) in self.areas.items():
            if not (min_lon < max_lon and min_lat < max_lat):
                problems.append(f"area {name}: expected min_lon, min_lat, max_lon, max_lat")
        for code, source in self.sources.items():
            if code != source.code:
                problems.append(f"source {code}: the table name and code differ")
        names = [dataset.name for dataset in self.datasets]
        for name in sorted({name for name in names if names.count(name) > 1}):
            problems.append(f"dataset {name} is defined twice")
        for dataset in self.datasets:
            if dataset.source not in self.sources:
                problems.append(f"dataset {dataset.name}: unknown source {dataset.source}")
            if dataset.area not in self.areas:
                problems.append(f"dataset {dataset.name}: unknown area {dataset.area}")
            if dataset.qa.expected_area is not None and dataset.qa.expected_area not in self.areas:
                problems.append(f"dataset {dataset.name}: unknown expected_area {dataset.qa.expected_area}")
        if self.basemap is not None:
            for referenced in (self.basemap.osm_source, self.basemap.land_source, self.basemap.glyphs_source):
                if referenced is not None and referenced not in self.sources:
                    problems.append(f"basemap: unknown source {referenced}")
            if self.basemap.detail_area not in self.areas:
                problems.append(f"basemap: unknown area {self.basemap.detail_area}")
            if self.basemap.min_zoom > self.basemap.max_zoom:
                problems.append("basemap: min_zoom is larger than max_zoom")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def area(self, name: str) -> BBox:
        return self.areas[name]

    def expectations(self, dataset: DatasetConfig) -> QaExpectations:
        stated = dataset.qa.model_dump(exclude_unset=True)
        area = stated.pop("expected_area", None)
        if area is not None:
            stated["expected_bbox"] = self.areas[area]
        return QaExpectations.model_validate(stated)


def load_profile(path: Path) -> Profile:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProfileError(f"cannot read profile {path}: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"profile {path.name} is not valid TOML: {exc}") from exc
    sources = document.get("sources", {})
    if isinstance(sources, dict):
        document["sources"] = {
            code: {"code": code, **values} if isinstance(values, dict) else values
            for code, values in sources.items()
        }
    document["directory"] = path.resolve().parent
    try:
        return Profile.model_validate(document)
    except ValidationError as exc:
        raise ProfileError(
            f"invalid profile {path.name}", extensions={"errors": validation_problems(exc)}
        ) from exc


def check_licences(profile: Profile) -> list[str]:
    """Refuse sources whose licences do not permit the use; return notes about obligations (share-alike)."""
    used = {dataset.source for dataset in profile.datasets}
    if profile.basemap is not None:
        used |= {profile.basemap.osm_source, profile.basemap.land_source}
        if profile.basemap.glyphs_source is not None:
            used.add(profile.basemap.glyphs_source)
    production = profile.profile.purpose == "production"
    problems: list[str] = []
    notes: list[str] = []
    for code in sorted(used):
        source = profile.sources[code]
        if source.review.status == "rejected":
            problems.append(f"{code}: its licence review was rejected ({source.review.reference})")
        if not source.commercial_use_allowed and not source.permission_reference:
            problems.append(
                f"{code}: its licence does not permit commercial use; record the licensor's written "
                "permission (permission_reference) or leave the source out"
            )
        if RESTRICTED_LICENCE.search(source.licence) and not source.permission_reference:
            problems.append(
                f"{code}: licence {source.licence} restricts commercial use, redistribution or derived data; "
                "record the licensor's written permission (permission_reference) or leave the source out"
            )
        if production and source.review.status != "approved":
            problems.append(f"{code}: a production profile needs an approved licence review for every source")
        if not source.redistribution_allowed:
            notes.append(f"{code}: the data may not leave the platform; exports of its layers are refused")
        if source.share_alike:
            notes.append(
                f"{code}: {source.licence} is share-alike; derived databases shared outside the platform "
                "must be offered under the same licence"
            )
    if production:
        for dataset in profile.datasets:
            source = profile.sources[dataset.source]
            if (
                dataset.adapter == "placeholder"
                or (dataset.geometry_source or source.geometry_source) == "synthetic"
            ):
                problems.append(
                    f"dataset {dataset.name}: placeholder or synthetic data cannot be in a production release"
                )
    if problems:
        raise LicenceError(
            "the profile uses sources it may not use: " + "; ".join(problems),
            extensions={"problems": problems},
        )
    return notes


def raw_path(raw_dir: Path, source: SourceConfig, profile_dir: Path | None = None) -> Path:
    path = Path(source.file)
    if path.is_absolute():
        return path
    if source.base == "profile":
        if profile_dir is None:
            raise ProfileError(
                f"source {source.code}: its file is relative to the profile, whose directory is unknown"
            )
        return (profile_dir / path).resolve()
    return raw_dir / path
