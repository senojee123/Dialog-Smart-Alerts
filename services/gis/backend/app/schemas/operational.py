"""Tenant-owned operational GIS objects: geofences, sites and device placements (plan §5.2, §7).

These are the parts of the map a tenant maintains itself. They are geographic objects, nothing more: a
geofence is an area with a validity period, not a rule about who gets told when something happens in it.
The GIS service reports that an event lies in a geofence; what follows from that is outside this service
(ADR-0012).

Ownership and sharing:

* every object belongs to exactly one tenant, and only that tenant may change or delete it
* ``sharingPolicy`` decides who else may read it: ``private`` (nobody), ``shared`` (the tenants in
  ``sharedWithTenants``, and authority tenants), ``authority_only`` (authority tenants)
* the database enforces this with row-level security, so a query can never reach another tenant's
  private objects even if an identifier is guessed

Versioning: ``version`` counts changes to an object. An update must state the version it is based on and
fails with 409 if the object has changed since - so two editors cannot overwrite each other unnoticed.
Geo-context hits record the geofence version they were computed against, which is what makes a stored
hit reproducible.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Final, Literal, Self, get_args

from pydantic import AwareDatetime, Field, model_validator

from app.core.paging import MAX_CURSOR_CHARS
from app.core.tenancy import TENANT_ID_PATTERN
from app.schemas.base import ApiModel
from app.schemas.geojson import GeoJsonGeometry
from app.spatial.layers import DEVICE_STATUSES, GEOFENCE_KINDS, GEOFENCE_STATUSES, SITE_STATUSES

MAX_ATTRIBUTE_BYTES: Final = 16_384
MAX_SHARED_TENANTS: Final = 100
MAX_CIRCLE_RADIUS_M: Final = 50_000.0
MAX_CORRIDOR_HALF_WIDTH_M: Final = 5_000.0
MAX_MOUNTING_HEIGHT_M: Final = 500.0
MAX_FIELD_OF_VIEW_RANGE_M: Final = 10_000.0

SharingPolicy = Literal["private", "shared", "authority_only"]
GeofenceKind = Literal["polygon", "circle", "corridor"]
GeofenceStatus = Literal["draft", "active", "suspended", "archived"]
SiteStatus = Literal["planned", "active", "decommissioned"]
SiteType = Literal["pole", "building", "junction", "checkpoint", "estate", "perimeter", "other"]
DeviceStatus = Literal["planned", "active", "inactive", "decommissioned"]
DeviceType = Literal[
    "camera",
    "anpr_camera",
    "acoustic_sensor",
    "seismic_sensor",
    "environmental_sensor",
    "gateway",
    "other",
]
PositionSource = Literal["survey", "gps", "digitised", "imagery", "estimated"]
FieldOfViewMethod = Literal["modelled", "surveyed"]

# The Literals above must stay the values the database accepts (see migration 20260915_0004); the layer
# registry carries the same lists for filtering, so the two are checked against each other at import.
assert set(GEOFENCE_KINDS) == set(get_args(GeofenceKind))
assert set(GEOFENCE_STATUSES) == set(get_args(GeofenceStatus))
assert set(SITE_STATUSES) == set(get_args(SiteStatus))
assert set(DEVICE_STATUSES) == set(get_args(DeviceStatus))

_TENANT_ID: Final = re.compile(TENANT_ID_PATTERN)
_POLYGON_TYPES: Final = frozenset({"Polygon", "MultiPolygon"})
_LINE_TYPES: Final = frozenset({"LineString", "MultiLineString"})


def _check_attributes(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()) > MAX_ATTRIBUTE_BYTES:
        raise ValueError(f"attributes must not exceed {MAX_ATTRIBUTE_BYTES} bytes as JSON")
    return value


def attributes_field() -> Any:
    return Field(
        default_factory=dict,
        description=f"Free-form properties of your own (JSON object, at most {MAX_ATTRIBUTE_BYTES} bytes). "
        "The GIS service stores them and does not interpret them.",
    )


class Ownership(ApiModel):
    """Who may read an object besides its owner."""

    sharing_policy: SharingPolicy = Field(
        default="private",
        description="`private`: the owning tenant only. `shared`: also the tenants in "
        "`sharedWithTenants` and authority tenants. `authority_only`: also authority tenants.",
    )
    shared_with_tenants: list[str] = Field(
        default_factory=list,
        max_length=MAX_SHARED_TENANTS,
        description="Tenants that may read this object; only with `sharingPolicy` `shared`.",
    )

    @model_validator(mode="after")
    def _sharing_is_consistent(self) -> Self:
        if self.shared_with_tenants and self.sharing_policy != "shared":
            raise ValueError("sharedWithTenants requires sharingPolicy 'shared'")
        for tenant_id in self.shared_with_tenants:
            if not _is_tenant_id(tenant_id):
                raise ValueError(f"{tenant_id!r} is not a tenant id")
        if len(set(self.shared_with_tenants)) != len(self.shared_with_tenants):
            raise ValueError("sharedWithTenants must not repeat a tenant")
        return self


def _is_tenant_id(value: str) -> bool:
    return _TENANT_ID.fullmatch(value) is not None


class Period(ApiModel):
    """A half-open period: ``from`` is included, ``to`` is not. An open end means "until further notice"."""

    time_from: AwareDatetime | None = Field(
        default=None, alias="from", description="Start; default: the moment the object is created."
    )
    time_to: AwareDatetime | None = Field(default=None, alias="to", description="End; null: open.")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.time_from is not None and self.time_to is not None and self.time_to <= self.time_from:
            raise ValueError("'to' must be after 'from'")
        return self


class GeofenceDefinition(ApiModel):
    """A geofence as its author defined it. This is what is stored and what hits are tested against.

    * `polygon`: a Polygon or MultiPolygon area
    * `circle`: a Point centre and `radiusM`
    * `corridor`: a LineString or MultiLineString centre line and `radiusM` as the half-width

    For circles and corridors the database also derives a polygon for display and for the spatial index,
    but the exact test always uses the definition and the radius, so a hit is not an approximation.
    """

    kind: GeofenceKind
    geometry: GeoJsonGeometry = Field(description="WGS84, [longitude, latitude].")
    radius_m: float | None = Field(
        default=None,
        gt=0,
        le=MAX_CIRCLE_RADIUS_M,
        description=f"Circle radius, or corridor half-width, in metres. Circles: at most "
        f"{MAX_CIRCLE_RADIUS_M:.0f}; corridors: at most {MAX_CORRIDOR_HALF_WIDTH_M:.0f}. Must be absent "
        "for a polygon.",
    )

    @model_validator(mode="after")
    def _matches_kind(self) -> Self:
        geometry_type = self.geometry.type
        if self.kind == "polygon":
            if geometry_type not in _POLYGON_TYPES:
                raise ValueError("a polygon geofence needs a Polygon or MultiPolygon")
            if self.radius_m is not None:
                raise ValueError("a polygon geofence has no radiusM")
            return self
        if self.radius_m is None:
            raise ValueError(f"a {self.kind} geofence needs radiusM")
        if self.kind == "circle":
            if geometry_type != "Point":
                raise ValueError("a circle geofence needs a Point centre")
        elif geometry_type not in _LINE_TYPES:
            raise ValueError("a corridor geofence needs a LineString or MultiLineString centre line")
        if self.kind == "corridor" and self.radius_m > MAX_CORRIDOR_HALF_WIDTH_M:
            raise ValueError(f"a corridor half-width must not exceed {MAX_CORRIDOR_HALF_WIDTH_M:.0f} metres")
        return self


class GeofenceIn(Ownership):
    """A geofence to create."""

    name: str = Field(min_length=1, max_length=200, examples=["Habarana junction watch zone"])
    description: str | None = Field(default=None, max_length=1000)
    external_id: str | None = Field(
        default=None, max_length=200, description="Identifier of this geofence in your own system."
    )
    definition: GeofenceDefinition
    status: GeofenceStatus = Field(
        default="active",
        description="Only `active` geofences produce geo-context hits; `draft` and `suspended` ones are "
        "stored but not tested, `archived` ones are retired.",
    )
    effective_during: Period = Field(
        default_factory=Period, description="Period in which the geofence produces hits."
    )
    attributes: dict[str, Any] = attributes_field()

    @model_validator(mode="after")
    def _attributes_fit(self) -> Self:
        _check_attributes(self.attributes)
        return self


class GeofenceUpdate(GeofenceIn):
    """A geofence as it should be after the change, based on the version read before."""

    version: int = Field(
        ge=1,
        description="Version this change is based on (from the object you read). If the geofence has "
        "changed since, the request is refused with 409.",
    )


class GeofenceOut(ApiModel):
    model_config = ApiModel.model_config | {"json_schema_serialization_defaults_required": True}

    id: uuid.UUID
    tenant_id: str = Field(description="Tenant that owns the geofence.")
    name: str
    description: str | None
    external_id: str | None
    definition: GeofenceDefinition
    area_m2: float = Field(description="Area in square metres (exact for circles).")
    status: GeofenceStatus
    effective_during: Period
    sharing_policy: SharingPolicy
    shared_with_tenants: list[str]
    attributes: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class SiteIn(Ownership):
    """An installation site: a pole, building, junction or other fixed place."""

    name: str = Field(min_length=1, max_length=200, examples=["Habarana junction pole 3"])
    external_id: str | None = Field(default=None, max_length=200)
    site_type: SiteType = "other"
    status: SiteStatus = "active"
    position: GeoJsonGeometry = Field(description="A GeoJSON Point (WGS84, [longitude, latitude]).")
    position_source: PositionSource = Field(description="How the position was obtained.")
    position_accuracy_m: float | None = Field(
        default=None, gt=0, le=10_000, description="Estimated horizontal accuracy in metres."
    )
    attributes: dict[str, Any] = attributes_field()

    @model_validator(mode="after")
    def _is_a_point(self) -> Self:
        if self.position.type != "Point":
            raise ValueError("a site position must be a Point")
        _check_attributes(self.attributes)
        return self


class SiteUpdate(SiteIn):
    version: int = Field(ge=1, description="Version this change is based on.")


class SiteOut(ApiModel):
    model_config = ApiModel.model_config | {"json_schema_serialization_defaults_required": True}

    id: uuid.UUID
    tenant_id: str
    name: str
    external_id: str | None
    site_type: SiteType
    status: SiteStatus
    position: GeoJsonGeometry
    position_source: PositionSource
    position_accuracy_m: float | None
    sharing_policy: SharingPolicy
    shared_with_tenants: list[str]
    attributes: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class FieldOfViewIn(ApiModel):
    """What a camera or sensor observes from its position.

    `modelled`: the database computes the sector from `bearingDeg`, `fovDeg` and `rangeM`, and keeps it up
    to date when the device moves. `surveyed`: you supply the observed area as a polygon.
    """

    method: FieldOfViewMethod = "modelled"
    bearing_deg: float | None = Field(
        default=None, ge=0, lt=360, description="Viewing direction, degrees clockwise from north."
    )
    fov_deg: float | None = Field(
        default=None, gt=0, le=360, description="Horizontal angle in degrees (360 for omnidirectional)."
    )
    range_m: float | None = Field(
        default=None, gt=0, le=MAX_FIELD_OF_VIEW_RANGE_M, description="Effective detection range in metres."
    )
    geometry: GeoJsonGeometry | None = Field(
        default=None, description="Observed area as a Polygon or MultiPolygon (`surveyed` only)."
    )

    @model_validator(mode="after")
    def _matches_method(self) -> Self:
        if self.method == "modelled":
            if None in (self.bearing_deg, self.fov_deg, self.range_m):
                raise ValueError("a modelled field of view needs bearingDeg, fovDeg and rangeM")
            if self.geometry is not None:
                raise ValueError("a modelled field of view is computed; do not send a geometry")
            return self
        if self.geometry is None or self.geometry.type not in _POLYGON_TYPES:
            raise ValueError("a surveyed field of view needs a Polygon or MultiPolygon geometry")
        return self


class FieldOfViewOut(ApiModel):
    id: uuid.UUID
    method: FieldOfViewMethod
    bearing_deg: float | None
    fov_deg: float | None
    range_m: float | None
    geometry: dict[str, Any] | None = Field(description="The observed area (GeoJSON, WGS84).")
    valid_during: Period


class DevicePlacementIn(Ownership):
    """Where a device is, and what it observes from there.

    Sending this for an identifier that does not exist yet registers the device (201); sending it again
    moves it (200). Moving a device keeps its open modelled field of view aligned with the new position.
    """

    name: str = Field(min_length=1, max_length=200, examples=["HB-CAM-01"])
    device_type: DeviceType
    external_id: str | None = Field(default=None, max_length=200)
    status: DeviceStatus = "active"
    site_id: uuid.UUID | None = Field(default=None, description="Site the device is installed at.")
    position: GeoJsonGeometry = Field(description="A GeoJSON Point (WGS84, [longitude, latitude]).")
    position_source: PositionSource
    position_accuracy_m: float | None = Field(default=None, gt=0, le=10_000)
    mounting_height_m: float | None = Field(default=None, ge=0, le=MAX_MOUNTING_HEIGHT_M)
    installed_at: AwareDatetime | None = None
    decommissioned_at: AwareDatetime | None = None
    field_of_view: FieldOfViewIn | None = Field(
        default=None,
        description="Replace the field of view in effect: the current period is closed now and this one "
        "starts. Omit to leave it as it is.",
    )
    attributes: dict[str, Any] = attributes_field()
    version: int | None = Field(
        default=None,
        ge=1,
        description="Version this change is based on. Required when the device exists; omit when "
        "registering a new one.",
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.position.type != "Point":
            raise ValueError("a device position must be a Point")
        if (
            self.installed_at is not None
            and self.decommissioned_at is not None
            and self.decommissioned_at < self.installed_at
        ):
            raise ValueError("decommissionedAt must not be before installedAt")
        _check_attributes(self.attributes)
        return self


class DevicePlacementOut(ApiModel):
    model_config = ApiModel.model_config | {"json_schema_serialization_defaults_required": True}

    id: uuid.UUID
    tenant_id: str
    name: str
    device_type: DeviceType
    external_id: str | None
    status: DeviceStatus
    site_id: uuid.UUID | None
    position: GeoJsonGeometry
    position_source: PositionSource
    position_accuracy_m: float | None
    mounting_height_m: float | None
    installed_at: datetime | None
    decommissioned_at: datetime | None
    sharing_policy: SharingPolicy
    shared_with_tenants: list[str]
    attributes: dict[str, Any]
    field_of_view: FieldOfViewOut | None = Field(
        description="The field of view in effect now, if the device has one."
    )
    version: int
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    updated_by: str | None


class GeofenceListOut(ApiModel):
    items: list[GeofenceOut]
    count: int
    next_cursor: str | None = Field(default=None, description="Cursor for the next page; null at the end.")


class SiteListOut(ApiModel):
    items: list[SiteOut]
    count: int
    next_cursor: str | None = None


class OperationalListQuery(ApiModel):
    """Query parameters for listing geofences or sites."""

    status: str | None = Field(default=None, max_length=50, description="Lifecycle status.")
    kind: str | None = Field(
        default=None, max_length=50, description="Geofence kind: polygon, circle or corridor."
    )
    site_type: str | None = Field(default=None, max_length=50, description="Site type.")
    name_contains: str | None = Field(default=None, max_length=100)
    bbox: str | None = Field(
        default=None, max_length=120, description="Viewport as `minLon,minLat,maxLon,maxLat` in WGS84."
    )
    at: AwareDatetime | None = Field(
        default=None, description="Only geofences in effect at this instant (geofences only)."
    )
    owned_only: bool = Field(
        default=False, description="Only objects this tenant owns, leaving out those shared with it."
    )
    tenant_id: str | None = Field(
        default=None,
        alias="tenantId",
        pattern=TENANT_ID_PATTERN,
        description="Tenant whose objects to list: the one the request acts for. It may be omitted.",
        examples=["wildlife-dept"],
    )
    limit: int = Field(default=100, ge=1, le=1000)
    cursor: str | None = Field(default=None, max_length=MAX_CURSOR_CHARS)
