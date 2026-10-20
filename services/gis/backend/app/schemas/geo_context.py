"""Geo-context document (schema ``geo-context/1``).

The geographic facts the GIS service attaches to an event (plan §5.3). The document is stored in
``geo.event_geo_context.document`` and returned by ``POST /geo/v1/enrich``. It describes places only;
it names no recipients and implies no action.

Determinism: for the same event, reference data release and tenant-visible operational data, every
member except ``computedAt`` is identical. Lists have a fixed order and ties are broken by id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Final, Literal

from pydantic import AwareDatetime, Field

from app.schemas.base import ApiModel

GEO_CONTEXT_SCHEMA_VERSION: Final = "geo-context/1"

Relation = Literal["within", "intersects"]
ZoneType = Literal["protected_area", "risk_zone"]
GeofenceKind = Literal["polygon", "circle", "corridor"]
SettlementBasis = Literal["point", "footprint"]
GeometryKind = Literal["point", "line", "area"]
LocationSource = Literal["device", "estimated", "sensor", "external"]
ReferenceLayerName = Literal["admin_area", "settlement", "road", "protected_area", "risk_zone"]

# Reference layers the geo-context reads, in document order (``missingLayers``).
CONTEXT_REFERENCE_LAYERS: Final[tuple[ReferenceLayerName, ...]] = (
    "admin_area",
    "settlement",
    "road",
    "protected_area",
    "risk_zone",
)

_RELATION = (
    "`within`: the whole event geometry lies inside (always the case for a point that matches); "
    "`intersects`: a line or area event crosses the boundary."
)


class AdminAreaRef(ApiModel):
    id: uuid.UUID
    code: str = Field(examples=["LK7"])
    name: str = Field(examples=["North Central Province"])
    name_si: str | None = Field(description="Sinhala name, when the release has one.")
    name_ta: str | None = Field(description="Tamil name, when the release has one.")
    level: int = Field(ge=0, le=4, description="1 province, 2 district, 3 DS division, 4 GN division.")
    level_name: str = Field(examples=["province"])


class AdminCodes(ApiModel):
    """Codes of the admin hierarchy, for attribute rules (``admin.codes.l4 == ...``)."""

    l1: str | None = Field(description="Province code.")
    l2: str | None = Field(description="District code.")
    l3: str | None = Field(description="DS division code.")
    l4: str | None = Field(description="GN division code.")


class AdminHierarchy(ApiModel):
    province: AdminAreaRef | None
    district: AdminAreaRef | None
    ds_division: AdminAreaRef | None
    gn_division: AdminAreaRef | None
    codes: AdminCodes
    on_boundary: bool = Field(
        description="The reference location lies on a boundary shared by areas of the same level; "
        "the area with the lowest code was chosen."
    )


class NearestSettlement(ApiModel):
    id: uuid.UUID
    name: str
    name_si: str | None
    name_ta: str | None
    settlement_type: str = Field(examples=["town"])
    basis: SettlementBasis = Field(
        description="`footprint`: distance to the built-up area (0 inside it); `point`: distance to the "
        "settlement's point."
    )
    distance_m: float = Field(ge=0, description="Metres (EPSG:5235), rounded to 0.01 m.")


class NearestRoad(ApiModel):
    id: uuid.UUID
    name: str | None
    road_class: str = Field(alias="class", examples=["A"], description="Road class (A, B, E, ...).")
    ref_code: str | None = Field(examples=["A11"])
    distance_m: float = Field(ge=0, description="Metres (EPSG:5235), rounded to 0.01 m.")


class ZoneHit(ApiModel):
    id: uuid.UUID
    zone_type: ZoneType = Field(alias="type")
    name: str
    category: str = Field(description="Designation of a protected area, or risk type of a risk zone.")
    severity: int | None = Field(description="Risk zones only: 1 (low) to 5 (high).")
    relation: Relation = Field(description=_RELATION)


class GeofenceHit(ApiModel):
    id: uuid.UUID
    name: str
    kind: GeofenceKind
    tenant_id: str = Field(description="Tenant that owns the geofence (shared geofences belong to others).")
    version: int = Field(ge=1, description="Geofence version the event was tested against.")
    relation: Relation = Field(description=_RELATION)


class NearbyDevice(ApiModel):
    device_id: uuid.UUID
    name: str
    device_type: str = Field(examples=["camera"])
    tenant_id: str = Field(description="Tenant that owns the device.")
    distance_m: float = Field(ge=0, description="Metres (EPSG:5235), rounded to 0.01 m.")
    in_field_of_view: bool | None = Field(
        description="The event geometry intersects the device's field of view in effect at `observedAt`; "
        "null when the device has no field of view then."
    )


class SearchLimits(ApiModel):
    """Search radii (inclusive) and result size used for the proximity members."""

    settlement_radius_m: float
    road_radius_m: float
    device_radius_m: float
    device_limit: int


class GeoContext(ApiModel):
    # Every member is always present in responses, including those with defaults.
    model_config = ApiModel.model_config | {"json_schema_serialization_defaults_required": True}

    schema_id: Literal["geo-context/1"] = Field(
        default=GEO_CONTEXT_SCHEMA_VERSION, alias="schema", description="Document schema and version."
    )
    event_id: str
    tenant_id: str
    observed_at: AwareDatetime
    location_source: LocationSource
    geometry_kind: GeometryKind
    admin: AdminHierarchy = Field(
        description="Admin areas at the event point (lines and areas: at ST_PointOnSurface)."
    )
    nearest_settlement: NearestSettlement | None = Field(
        description="Nearest settlement within `search.settlementRadiusM`, else null."
    )
    nearest_road: NearestRoad | None = Field(
        description="Nearest road within `search.roadRadiusM`, else null."
    )
    inside_zones: list[ZoneHit] = Field(
        description="Protected areas and risk zones (valid at `observedAt`) the event lies in, by type, "
        "name and id."
    )
    geofence_hits: list[GeofenceHit] = Field(
        description="Active geofences visible to the tenant that the event lies in, by name and id."
    )
    nearest_devices: list[NearbyDevice] = Field(
        description="Active devices visible to the tenant within `search.deviceRadiusM`, nearest first, "
        "excluding the device that reported the event."
    )
    missing_layers: list[ReferenceLayerName] = Field(
        description="Reference layers without any features in `refDataRelease`. An empty or null result "
        "for such a layer says nothing about the location."
    )
    search: SearchLimits
    ref_data_release: str = Field(
        description="Reference data release the context was computed with.", examples=["ref-2026.10"]
    )
    computed_at: datetime
