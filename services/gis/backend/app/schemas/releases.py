"""Reference data releases as the API shows them: what a release contains and where every dataset came from.

Only published and retired releases are listed (a draft is still being loaded and checked). The lineage
is the one recorded when the data was loaded: licences and attribution as they were at that time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel

ReleaseStatus = Literal["published", "retired"]


class ReleaseSummary(ApiModel):
    code: str = Field(examples=["ref-2026.09-dev"])
    status: ReleaseStatus
    purpose: Literal["production", "development", "test"] = Field(
        description="Development and test releases may hold open development data and labelled placeholders."
    )
    is_current: bool = Field(description="The release used when a request names none.")
    description: str | None
    published_at: datetime | None
    retired_at: datetime | None
    datasets: int = Field(description="Datasets (loaded files) in the release.")
    features: int = Field(description="Features loaded, over all layers.")


class ReleaseList(ApiModel):
    releases: list[ReleaseSummary]


class DatasetLineage(ApiModel):
    """One dataset of a release: source, licence, version, import, CRS, geometry, accuracy and counts."""

    layer: str = Field(examples=["ref.road"])
    source: str = Field(description="Code of the data source.", examples=["osm-geofabrik-lka"])
    source_name: str
    publisher: str
    licence: str = Field(description="Licence when the data was imported (SPDX where one exists).")
    licence_url: str | None
    attribution: str
    commercial_use_allowed: bool
    redistribution_allowed: bool = Field(description="False: exports of this layer are refused.")
    share_alike: bool
    licence_review: Literal["unreviewed", "approved", "rejected"]
    source_reference: str = Field(description="URL or reference of the exact file or delivery.")
    source_version: str | None
    source_retrieved_at: datetime | None
    source_file: str = Field(description="GIS-ready file that was loaded.")
    source_checksum_sha256: str
    original_file: str | None = Field(description="File as received from the source.")
    original_checksum_sha256: str | None
    source_crs: str
    storage_crs: str
    coordinate_operation: str | None = Field(description="Operation from the source CRS; null when none.")
    transformation: str = Field(description="What the pipeline did to the data.")
    geometry_types: list[str]
    geometry_accuracy_m: float | None = Field(description="Nominal horizontal accuracy in metres.")
    source_features: int
    loaded: int
    repaired: int
    rejected: int
    imported_at: datetime
    finished_at: datetime | None


class ArtifactSource(ApiModel):
    source: str
    role: str
    licence: str
    attribution: str
    version: str | None
    reference: str


class ReleaseArtifactOut(ApiModel):
    """A file built for the release that is not a table: the basemap tiles, style and glyphs."""

    kind: Literal["basemap_tiles", "basemap_style", "basemap_glyphs"]
    name: str
    uri: str = Field(description="Where the web server serves it.")
    media_type: str
    sha256: str
    size_bytes: int
    crs: str
    min_zoom: int | None
    max_zoom: int | None
    sources: list[ArtifactSource]


class ReleaseQa(ApiModel):
    """The database QA run the release was published after."""

    status: Literal["passed", "warnings", "failed"]
    finished_at: datetime | None
    checks: int
    errors: int
    warnings: int
    infos: int
    waived_errors: int = Field(description="Errors an operator accepted, with a recorded reason.")


class ReleaseDetail(ReleaseSummary):
    attribution: list[str] = Field(description="Every attribution the release's sources require.")
    dataset_lineage: list[DatasetLineage] = Field(description="Every dataset with its lineage and licence.")
    artifacts: list[ReleaseArtifactOut]
    qa: ReleaseQa | None
