"""What the audit log records about a read, and when (ADR-0017).

The rules, in one place:

* every spatial question - within a distance, nearest, containing - and every reverse geocoding is a
  **search**, whatever layer it asks about;
* every read of tenant operational data (features of an ``ops.*`` layer, geofences, sites, device
  placements) and every event query is a **sensitive query**;
* reading reference data by viewport alone is neither, and is not recorded: it is the same public data
  for every tenant and a map reads it on every pan. Reading it by name (``nameContains``) is a search;
* every **export** is recorded;
* reading the audit log is itself a sensitive query.

Changes (geofences, sites, device placements) and reference data releases are recorded by database
triggers (migration 20260923_0007), not here, so no code path can skip them.

A record carries the layer, filters, distances, windows and paging of the request. A geometry or bounding
box is passed on as WKB and reduced by the database to its type and coarse extent (``audit.coarse_extent``,
about 110 m): the log shows roughly where someone searched, without keeping the exact position, which may
be a person's.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import shapely

from app.repositories.audit import AuditCategory, AuditRecord
from app.repositories.spatial_lookup import ReleaseRow
from app.schemas.spatial_query import (
    EventListQuery,
    EventQueryWindow,
    EventSelection,
    FeatureListQuery,
    FeatureSelection,
    SpatialQuery,
)
from app.spatial.layers import SpatialLayer
from app.spatial.validation import Bbox

EVENT_TARGET = "geo.event_location"


def bbox_wkb(bbox: Bbox | None) -> bytes | None:
    return None if bbox is None else shapely.box(*bbox).wkb


def _release_code(release: ReleaseRow | None) -> str | None:
    return None if release is None else release.code


def _selection_parameters(
    params: FeatureSelection, at: datetime | None, release: ReleaseRow | None
) -> dict[str, Any]:
    return {
        "filters": params.as_mapping(),
        "nameContains": params.name_contains,
        "at": at,
        "refDataRelease": _release_code(release),
    }


def feature_read(
    layer: SpatialLayer,
    params: FeatureListQuery,
    bbox: Bbox | None,
    at: datetime | None,
    release: ReleaseRow | None,
    count: int,
    *,
    continued: bool,
) -> AuditRecord | None:
    """A page of a layer's features: recorded for tenant data and for searches by name."""
    category: AuditCategory
    if layer.scope == "tenant":
        category = "sensitive_query"
    elif params.name_contains is not None:
        category = "search"
    else:
        return None
    return AuditRecord(
        category=category,
        operation="features.list",
        target=layer.code,
        geometry_wkb=bbox_wkb(bbox),
        parameters={
            **_selection_parameters(params, at, release),
            "limit": params.limit,
            "continued": continued or None,
        },
        result_count=count,
    )


def feature_export(
    layer: SpatialLayer,
    params: FeatureSelection,
    bbox: Bbox | None,
    at: datetime | None,
    release: ReleaseRow | None,
    count: int,
) -> AuditRecord:
    return AuditRecord(
        category="export",
        operation="export.features",
        target=layer.code,
        geometry_wkb=bbox_wkb(bbox),
        parameters={**_selection_parameters(params, at, release), "format": "geojson"},
        result_count=count,
    )


def spatial_question(
    operation: str,
    layer: SpatialLayer,
    query: SpatialQuery,
    geometry_wkb: bytes,
    at: datetime | None,
    release: ReleaseRow | None,
    count: int,
    *,
    continued: bool,
    **parameters: Any,
) -> AuditRecord:
    return AuditRecord(
        category="search",
        operation=operation,
        target=layer.code,
        geometry_wkb=geometry_wkb,
        parameters={
            **parameters,
            "filters": query.filters.as_mapping(),
            "nameContains": query.name_contains,
            "at": at,
            "refDataRelease": _release_code(release),
            "continued": continued or None,
        },
        result_count=count,
    )


def reverse_geocode(geometry_wkb: bytes, release_code: str) -> AuditRecord:
    return AuditRecord(
        category="search",
        operation="query.reverse_geocode",
        target="ref.admin_area",
        geometry_wkb=geometry_wkb,
        parameters={"refDataRelease": release_code},
        result_count=1,
    )


def _event_parameters(params: EventSelection, window: EventQueryWindow) -> dict[str, Any]:
    return {
        "from": window.time_from,
        "to": window.time_to,
        "filters": params.as_mapping(),
        "geofenceId": params.geofence_id,
        "adminAreaId": params.admin_area_id,
        "adminAreaCode": params.admin_area_code,
    }


def event_read(
    params: EventListQuery, window: EventQueryWindow, bbox: Bbox | None, count: int, *, continued: bool
) -> AuditRecord:
    return AuditRecord(
        category="sensitive_query",
        operation="events.list",
        target=EVENT_TARGET,
        geometry_wkb=bbox_wkb(bbox),
        parameters={
            **_event_parameters(params, window),
            "limit": params.limit,
            "continued": continued or None,
        },
        result_count=count,
    )


def event_export(
    params: EventSelection, window: EventQueryWindow, bbox: Bbox | None, count: int
) -> AuditRecord:
    return AuditRecord(
        category="export",
        operation="export.events",
        target=EVENT_TARGET,
        geometry_wkb=bbox_wkb(bbox),
        parameters={**_event_parameters(params, window), "format": "geojson"},
        result_count=count,
    )


def operational_read(
    operation: str,
    target: str,
    count: int,
    *,
    object_id: str | None = None,
    bbox: Bbox | None = None,
    **parameters: Any,
) -> AuditRecord:
    """A read of geofences, sites or a device placement through the operational API."""
    return AuditRecord(
        category="sensitive_query",
        operation=operation,
        target=target,
        object_id=object_id,
        geometry_wkb=bbox_wkb(bbox),
        parameters=parameters,
        result_count=count,
    )
