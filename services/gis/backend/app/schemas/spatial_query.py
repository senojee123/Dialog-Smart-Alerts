"""Requests and responses of the spatial query API (plan §7).

The API answers geographic questions - what is here, what is near here, what contains this - and returns
features. It carries no notion of people, recipients or messages: a query selects *objects on a map*, and
the caller decides what to do with them.

Conventions:

* geometries in and out are GeoJSON (RFC 7946): WGS84, ``[longitude, latitude]``, no ``crs`` member.
  A request may state its CRS in ``crs`` for clarity; only WGS84 identifiers are accepted.
* distances and radii are metres, measured in EPSG:5235, and inclusive: a feature exactly at the given
  distance is part of the answer.
* collections are paged with an opaque ``nextCursor`` (keyset paging, see :mod:`app.core.paging`).
* answers about reference data carry ``refDataRelease``, the release they were computed from.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Final, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.core.paging import DEFAULT_LIMIT, MAX_CURSOR_CHARS, MAX_LIMIT
from app.core.tenancy import TENANT_ID_PATTERN
from app.schemas.base import ApiModel
from app.schemas.geo_context import (
    AdminHierarchy,
    NearestRoad,
    NearestSettlement,
    ReferenceLayerName,
)
from app.schemas.geojson import GeoJsonGeometry
from app.schemas.reference_data import RELEASE_CODE_PATTERN
from app.spatial.layers import CANONICAL_CRS, CRS_ALIASES, LAYER_CODE_PATTERN, Capability

MAX_DISTANCE_M: Final = 100_000.0
NEAREST_DEFAULT_LIMIT: Final = 10
NEAREST_MAX_LIMIT: Final = 100
NEAREST_DEFAULT_MAX_DISTANCE_M: Final = 25_000.0
MAX_NAME_SEARCH_CHARS: Final = 100
EVENT_DEFAULT_WINDOW_HOURS: Final = 24
EVENT_MAX_WINDOW_DAYS: Final = 31

Relation = Literal["within", "intersects"]
ContainmentMode = Literal["covers", "intersects"]


def cursor_field() -> Any:
    return Field(
        default=None,
        max_length=MAX_CURSOR_CHARS,
        description="Value of `nextCursor` from the previous page. Pass it back unchanged and keep every "
        "other parameter the same.",
    )


def limit_field() -> Any:
    return Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"Maximum number of features to return (at most {MAX_LIMIT}).",
    )


def release_field() -> Any:
    return Field(
        default=None,
        pattern=RELEASE_CODE_PATTERN,
        description="Reference data release to read; default: the current one.",
        examples=["ref-2026.09-lka-open"],
    )


def at_field() -> Any:
    return Field(
        default=None,
        description="Instant the layer's validity period must contain (risk zones, geofences, fields of "
        "view). Default: now. Rejected for layers without a validity period.",
    )


def tenant_field() -> Any:
    return Field(
        default=None,
        alias="tenantId",
        pattern=TENANT_ID_PATTERN,
        description="Tenant whose data this request concerns: the one the request acts for. It may be "
        "omitted. Reference layers need no tenant.",
        examples=["wildlife-dept"],
    )


def crs_field() -> Any:
    return Field(
        default=None,
        max_length=100,
        description="Coordinate reference system of `geometry`. GeoJSON is always WGS84, so only "
        f"`{CANONICAL_CRS}`, `CRS84` and the equivalent OGC URNs are accepted.",
    )


def _check_crs(value: str | None) -> str | None:
    if value is None:
        return None
    if value.strip().lower().replace(" ", "") in CRS_ALIASES:
        return value
    raise ValueError(
        f"unsupported coordinate reference system {value!r}; geometries must be WGS84 ({CANONICAL_CRS}), "
        "as GeoJSON requires"
    )


class LayerFilters(ApiModel):
    """Attribute filters. Which ones a layer supports is listed by `GET /geo/v1/layers`.

    A filter a layer does not have is rejected, so a typo cannot widen a result set silently.
    """

    type: str | None = Field(
        default=None,
        max_length=100,
        description="The layer's classifying attribute: settlement type, facility type, road class, water "
        "type, designation, risk type, site type, device type or geofence kind.",
    )
    status: str | None = Field(default=None, max_length=50, description="Lifecycle status of the feature.")
    level: int | None = Field(
        default=None, ge=0, le=4, description="Administrative level: 1 province, 2 district, 3 DS, 4 GN."
    )
    code: str | None = Field(default=None, max_length=50, description="Administrative area code.")
    parent_id: uuid.UUID | None = Field(default=None, description="Parent administrative area.")
    admin_area_id: uuid.UUID | None = Field(default=None, description="Administrative area of a settlement.")
    site_id: uuid.UUID | None = Field(default=None, description="Site a device is installed at.")
    device_id: uuid.UUID | None = Field(default=None, description="Device a field of view belongs to.")
    ref_code: str | None = Field(default=None, max_length=50, description="Road route number, e.g. A11.")
    severity: int | None = Field(default=None, ge=1, le=5, description="Risk zone severity.")
    managing_authority: str | None = Field(default=None, max_length=50)
    geometry_method: str | None = Field(default=None, max_length=50)

    def as_mapping(self) -> dict[str, Any]:
        """The filters that were set, keyed by the registry's filter names (camelCase on the wire)."""
        filters = {}
        for name, info in LayerFilters.model_fields.items():
            value = getattr(self, name)
            if value is not None:
                filters[info.alias or name] = value
        return filters


class SpatialQuery(ApiModel):
    """What every spatial query has: a target layer, a geometry and the scope to evaluate it in."""

    target: str = Field(
        pattern=LAYER_CODE_PATTERN,
        description="Layer to search, by its code from `GET /geo/v1/layers`.",
        examples=["ref.settlement"],
    )
    geometry: GeoJsonGeometry = Field(description="Geometry to search around (WGS84, [lon, lat]).")
    crs: str | None = crs_field()
    filters: LayerFilters = Field(default_factory=LayerFilters)
    name_contains: str | None = Field(
        default=None,
        max_length=MAX_NAME_SEARCH_CHARS,
        description="Case-insensitive substring of the feature name.",
    )
    ref_data_release: str | None = release_field()
    at: AwareDatetime | None = at_field()
    include_geometry: bool = Field(
        default=True, description="Return each feature's geometry; `false` returns properties only."
    )

    @field_validator("crs")
    @classmethod
    def _crs_is_wgs84(cls, value: str | None) -> str | None:
        return _check_crs(value)


class WithinDistanceQuery(SpatialQuery):
    """Objects within a distance of a geometry."""

    distance_m: float = Field(
        gt=0,
        le=MAX_DISTANCE_M,
        description=f"Search distance in metres, inclusive (at most {MAX_DISTANCE_M:.0f}).",
        examples=[500],
    )
    limit: int = limit_field()
    cursor: str | None = cursor_field()


class NearestQuery(SpatialQuery):
    """The nearest objects to a geometry, nearest first."""

    max_distance_m: float = Field(
        default=NEAREST_DEFAULT_MAX_DISTANCE_M,
        gt=0,
        le=MAX_DISTANCE_M,
        description="Do not look beyond this distance in metres. Bounding the search keeps it on the "
        "spatial index.",
    )
    limit: int = Field(
        default=NEAREST_DEFAULT_LIMIT,
        ge=1,
        le=NEAREST_MAX_LIMIT,
        description=f"How many features to return (at most {NEAREST_MAX_LIMIT}). Nearest queries are not "
        "paged; widen `maxDistanceM` or use `/query/within-distance` for large result sets.",
    )


class ContainsQuery(SpatialQuery):
    """Areas that contain a geometry (point-in-polygon and its generalisation)."""

    mode: ContainmentMode = Field(
        default="covers",
        description="`covers`: the area contains the whole geometry, boundary inclusive (a point on the "
        "boundary counts). `intersects`: the area and the geometry share any point.",
    )
    limit: int = limit_field()
    cursor: str | None = cursor_field()


class FeatureOut(ApiModel):
    """A GeoJSON Feature. `properties` holds the layer's exposed attributes, plus `distanceM` for
    distance queries and `relation` for containment queries."""

    type: Literal["Feature"] = "Feature"
    id: str
    geometry: dict[str, Any] | None
    properties: dict[str, Any]


class FeatureCollectionOut(ApiModel):
    """A GeoJSON FeatureCollection with the paging cursor and data lineage as foreign members."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[FeatureOut]
    count: int = Field(description="Number of features in this page.")
    layer: str | None = Field(default=None, description="Layer the features come from.")
    next_cursor: str | None = Field(
        default=None, description="Cursor for the next page; null on the last page."
    )
    ref_data_release: str | None = Field(
        default=None, description="Reference data release the features come from (reference layers only)."
    )


class LayerSummary(ApiModel):
    """A layer in the registry (``meta.layer``) and what the query API can do with it."""

    code: str = Field(examples=["ref.settlement"])
    name: str
    description: str
    layer_group: str = Field(examples=["reference"])
    geometry_types: list[str] = Field(examples=[["POINT", "MULTIPOLYGON"]])
    srid: int = Field(description="CRS features are served in (always 4326).")
    metric_srid: int = Field(description="CRS distances are measured in (EPSG:5235).")
    tenant_scoped: bool = Field(description="Operational layer: only the tenant's own and shared rows.")
    default_sharing_policy: str | None
    update_frequency: str
    nominal_accuracy_m: float | None
    queryable: bool = Field(description="The query API can read this layer.")
    capabilities: list[Capability] = Field(
        description="`features`, `within_distance`, `nearest`, `contains`."
    )
    filters: list[str] = Field(description="Attribute filters this layer accepts.")
    properties: list[str] = Field(description="Feature properties this layer returns.")
    time_filtered: bool = Field(description="The layer has a validity period, so `at` applies.")
    attribution: list[str] = Field(
        default_factory=list,
        description="Attribution the sources of this layer require, in the current release (reference "
        "layers). "
        "Show it wherever the layer is shown.",
    )
    exportable: bool = Field(
        default=True,
        description="False when a source's licence does not allow the data to leave the platform: exports "
        "of this layer are refused.",
    )


class LayerCatalogue(ApiModel):
    layers: list[LayerSummary]
    ref_data_release: str | None = Field(
        default=None, description="Current reference data release, for the reference layers."
    )
    attribution: list[str] = Field(
        default_factory=list, description="Every attribution the current reference data release requires."
    )


class ReverseGeocodeOut(ApiModel):
    """Where a position is: the administrative hierarchy and the nearest named places."""

    model_config = ApiModel.model_config | {"json_schema_serialization_defaults_required": True}

    point: GeoJsonGeometry = Field(description="The position that was resolved.")
    admin: AdminHierarchy
    nearest_settlement: NearestSettlement | None = Field(
        description="Nearest settlement within `settlementRadiusM`, else null."
    )
    nearest_road: NearestRoad | None = Field(description="Nearest road within `roadRadiusM`, else null.")
    settlement_radius_m: float
    road_radius_m: float
    missing_layers: list[ReferenceLayerName] = Field(
        description="Reference layers without features in `refDataRelease`; an empty result for such a "
        "layer says nothing about the position."
    )
    ref_data_release: str
    computed_at: datetime


class EventQueryWindow(ApiModel):
    """The time window an event query covers. Event storage is partitioned by month of `observedAt`, so a
    bounded window is what keeps a query on a few partitions."""

    time_from: AwareDatetime = Field(alias="from")
    time_to: AwareDatetime = Field(alias="to")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.time_to < self.time_from:
            raise ValueError("'to' must not be before 'from'")
        return self


class EventCollectionOut(FeatureCollectionOut):
    """Event locations as GeoJSON, newest first."""

    window: EventQueryWindow


class FeatureExportOut(FeatureCollectionOut):
    """An export: the complete selection as one GeoJSON FeatureCollection (never a partial page)."""

    exported_at: AwareDatetime = Field(description="When the export was made.")
    tenant_id: str | None = Field(
        default=None, description="Tenant the export was made for (operational layers)."
    )
    attribution: list[str] = Field(
        default_factory=list,
        description="Attribution the sources of the exported reference data require; keep it with the data.",
    )


class EventExportOut(FeatureExportOut):
    """An event export: every event of the window, newest first."""

    window: EventQueryWindow


class FeatureSelection(LayerFilters):
    """Which features of a layer: shared by the paged read and the export."""

    bbox: str | None = Field(
        default=None,
        max_length=120,
        description="Viewport as `minLon,minLat,maxLon,maxLat` in WGS84 degrees.",
        examples=["80.6,7.9,80.9,8.2"],
    )
    name_contains: str | None = Field(
        default=None,
        max_length=MAX_NAME_SEARCH_CHARS,
        description="Case-insensitive substring of the feature name.",
    )
    ref_data_release: str | None = release_field()
    at: AwareDatetime | None = at_field()
    tenant_id: str | None = tenant_field()


class FeatureListQuery(FeatureSelection):
    """Query parameters of ``GET /geo/v1/layers/{layer}/features``."""

    include_geometry: bool = Field(default=True, description="Return each feature's geometry.")
    limit: int = limit_field()
    cursor: str | None = cursor_field()


class FeatureExportQuery(FeatureSelection):
    """Query parameters of ``GET /geo/v1/layers/{layer}/export``: the whole selection, in one file."""


class EventSelection(ApiModel):
    """Which events: shared by the paged read and the export.

    The window defaults to the last 24 hours and is bounded: event storage is partitioned by month of
    `observedAt`, and a bounded window is what keeps a query on a few partitions.
    """

    time_from: AwareDatetime | None = Field(
        default=None, alias="from", description="Start of the window (inclusive). Default: `to` minus 24 h."
    )
    time_to: AwareDatetime | None = Field(
        default=None, alias="to", description="End of the window (exclusive). Default: now."
    )
    bbox: str | None = Field(
        default=None,
        max_length=120,
        description="Viewport as `minLon,minLat,maxLon,maxLat` in WGS84 degrees.",
        examples=["80.6,7.9,80.9,8.2"],
    )
    event_type: str | None = Field(default=None, max_length=100, examples=["wildlife.elephant_detected"])
    event_subtype: str | None = Field(default=None, max_length=100)
    source_type: str | None = Field(default=None, max_length=50)
    device_id: uuid.UUID | None = Field(default=None, description="Device that reported the events.")
    geofence_id: uuid.UUID | None = Field(
        default=None,
        description="Only events whose geo-context recorded a hit on this geofence (visible to the tenant).",
    )
    admin_area_id: uuid.UUID | None = Field(
        default=None, description="Only events whose geo-context places them in this administrative area."
    )
    admin_area_code: str | None = Field(
        default=None, max_length=50, description="The same filter by administrative area code, e.g. `LK71`."
    )
    tenant_id: str | None = tenant_field()

    def as_mapping(self) -> dict[str, Any]:
        """The event filters that were set, keyed by the names in :data:`app.spatial.layers.EVENTS`."""
        names = ("event_type", "event_subtype", "source_type", "device_id")
        filters = {}
        for name in names:
            value = getattr(self, name)
            if value is not None:
                filters[type(self).model_fields[name].alias or name] = value
        return filters


class EventListQuery(EventSelection):
    """Query parameters of ``GET /geo/v1/events``."""

    include_geometry: bool = Field(default=True, description="Return each event's geometry.")
    limit: int = limit_field()
    cursor: str | None = cursor_field()


class EventExportQuery(EventSelection):
    """Query parameters of ``GET /geo/v1/events/export``: every event of the window, in one file."""
