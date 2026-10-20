"""Event intake: what an event producer tells the GIS service about where an event happened.

The same model is used by every entry point (``POST /geo/v1/enrich`` today, an event-stream consumer
later), so an event validates identically however it arrives.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Final, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.core.tenancy import TENANT_ID_PATTERN
from app.schemas.base import ApiModel
from app.schemas.geo_context import LocationSource
from app.schemas.geojson import GeoJsonGeometry

EVENT_ID_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
EVENT_TYPE_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"
MAX_METADATA_BYTES: Final = 16_384
MAX_METADATA_DEPTH: Final = 8

SourceType = Literal["device", "sensor", "external", "manual"]


def _depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_depth(item) for item in value), default=0)
    return 0


class EventLocationIn(ApiModel):
    """An observed event and where it happened.

    ``location`` may be omitted when ``locationSource`` is ``device``: the installed position of the
    device is used. Point, line and area geometries are accepted (GeoJSON, WGS84, ``[lon, lat]``).
    Re-sending an event with the same ``tenantId``, ``eventId`` and ``observedAt`` replaces it.
    """

    event_id: str = Field(
        pattern=EVENT_ID_PATTERN, max_length=128, description="Producer's event id.", examples=["evt-000123"]
    )
    tenant_id: str = Field(
        pattern=TENANT_ID_PATTERN,
        description="Tenant the event belongs to. The caller must be authorised for this tenant.",
        examples=["wildlife-dept"],
    )
    observed_at: AwareDatetime = Field(
        description="When the event was observed (ISO 8601 with offset; normalised to UTC). At most 1 day in "
        "the future."
    )
    event_type: str = Field(
        pattern=EVENT_TYPE_PATTERN, max_length=100, examples=["wildlife.elephant_detected"]
    )
    event_subtype: str | None = Field(default=None, max_length=100)
    source_type: SourceType = Field(description="What produced the event.")
    device_id: uuid.UUID | None = Field(
        default=None,
        description="Registered GIS device that observed the event (required when sourceType is `device`).",
    )
    source_ref: str | None = Field(
        default=None,
        max_length=200,
        description="Identifier of the source in the producer's system (stream, feed, sensor).",
    )
    location_source: LocationSource = Field(
        description="How the location was obtained: `device` (device position or measured by the device), "
        "`estimated` (e.g. projected from a camera view), `sensor`, `external`."
    )
    location: GeoJsonGeometry | None = Field(
        default=None,
        description="GeoJSON geometry (Point, LineString, Polygon or their Multi forms). Optional only when "
        "locationSource is `device`.",
    )
    location_accuracy_m: float | None = Field(default=None, gt=0, le=100_000)
    field_of_view_id: uuid.UUID | None = Field(
        default=None, description="Field of view of the device to record; default: the one in effect."
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=f"Producer metadata, stored with the event (JSON object, at most {MAX_METADATA_BYTES} "
        f"bytes, nesting depth {MAX_METADATA_DEPTH}). The GIS service does not interpret it.",
    )

    @field_validator("observed_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        # One instant, one representation: the same event sent with another offset is the same event.
        return value.astimezone(UTC)

    @field_validator("metadata")
    @classmethod
    def _check_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()) > MAX_METADATA_BYTES:
            raise ValueError(f"metadata must not exceed {MAX_METADATA_BYTES} bytes as JSON")
        if _depth(value) > MAX_METADATA_DEPTH:
            raise ValueError(f"metadata must not be nested deeper than {MAX_METADATA_DEPTH} levels")
        return value

    @model_validator(mode="after")
    def _check_location(self) -> Self:
        if self.location_source == "device" and self.device_id is None:
            raise ValueError("locationSource 'device' requires deviceId")
        if self.location is None and self.location_source != "device":
            raise ValueError("location is required unless locationSource is 'device'")
        if self.source_type == "device" and self.device_id is None:
            raise ValueError("sourceType 'device' requires deviceId")
        if self.field_of_view_id is not None and self.device_id is None:
            raise ValueError("fieldOfViewId requires deviceId")
        return self
