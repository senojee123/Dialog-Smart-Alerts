"""The spatial query service: generic geospatial questions about places and events.

What it answers (plan §7): which features a layer has in a viewport, what lies within a distance of a
geometry, what the nearest features are, which areas contain a geometry, where a position is (reverse
geocoding), and which events were observed in a window and area.

What it deliberately does not do: it knows nothing about people, recipients, subscriptions or messages.
"Which objects are within 500 m of this point" is a spatial question and is answered; "who should be
notified" is not a spatial question and has no endpoint here (ADR-0012).

Every request goes through the same steps:

1. resolve the target layer in the registry (:mod:`app.spatial.layers`) - unknown layers are rejected
   rather than turned into SQL
2. validate what the request carries: CRS expectation, geometry (RFC 7946, service area, OGC validity),
   bounding box, filters the layer actually has, the paging cursor
3. resolve the reference data release (reference layers) or require a tenant (operational layers)
4. run one parameterised statement and return a GeoJSON FeatureCollection with the paging cursor and
   the release the answer came from
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import Access
from app.core.errors import (
    GisValidationError,
    NotFoundError,
    PermissionDeniedError,
    UnsupportedFilterError,
)
from app.core.paging import CursorValues, Page, build_page, cursor_of, fetch_limit, query_fingerprint
from app.core.tenancy import TenantId
from app.db.session import access_transaction, transaction
from app.repositories.audit import AuditRepository
from app.repositories.spatial_lookup import ReleaseRow
from app.repositories.spatial_query import (
    ContainmentQuery,
    DatasetTerms,
    DistanceQuery,
    EventQuery,
    EventRow,
    FeatureQuery,
    FeatureRow,
    LayerRow,
    SpatialQueryRepository,
)
from app.schemas.geojson import GeoJsonGeometry
from app.schemas.reference_data import merge_attribution
from app.schemas.spatial_query import (
    EVENT_DEFAULT_WINDOW_HOURS,
    EVENT_MAX_WINDOW_DAYS,
    ContainsQuery,
    EventCollectionOut,
    EventExportOut,
    EventExportQuery,
    EventListQuery,
    EventQueryWindow,
    EventSelection,
    FeatureCollectionOut,
    FeatureExportOut,
    FeatureExportQuery,
    FeatureListQuery,
    FeatureOut,
    FeatureSelection,
    LayerCatalogue,
    LayerSummary,
    NearestQuery,
    ReverseGeocodeOut,
    SpatialQuery,
    WithinDistanceQuery,
)
from app.services import audit_policy
from app.services.enrichment import GeoContextLimits, build_admin_hierarchy
from app.services.enrichment.assembly import metres, nearest_road_of, nearest_settlement_of
from app.services.releases import require_usable_release
from app.spatial.geometry import POINT_TYPES, ValidatedGeometry, parse_geojson_geometry
from app.spatial.layers import EVENTS, LAYERS_BY_CODE, SpatialLayer, ValueFilter
from app.spatial.service_area import ServiceArea
from app.spatial.validation import Bbox, parse_bbox

Clock = Callable[[], datetime]
EVENT_MAX_WINDOW: Final = timedelta(days=EVENT_MAX_WINDOW_DAYS)
EVENT_LAYER: Final = "geo.event_location"
DEFAULT_EXPORT_MAX_FEATURES: Final = 10_000
_EVENTS_NEED_A_TENANT: Final = "events belong to a tenant; name it in tenantId"


class LayerNotFoundError(NotFoundError):
    code = "layer_not_found"
    title = "Layer not found"


class UnsupportedQueryError(GisValidationError):
    """The layer cannot answer this kind of question (containment on a layer without areas, for example)."""

    code = "unsupported_query"
    title = "Query is not supported for this layer"


class TimeWindowError(GisValidationError):
    code = "time_window_too_large"
    title = "Time window is too large"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def resolve_layer(code: str) -> SpatialLayer:
    layer = LAYERS_BY_CODE.get(code)
    if layer is None:
        raise LayerNotFoundError(
            f"no queryable layer {code!r}; see GET /geo/v1/layers",
            extensions={"layer": code, "queryableLayers": sorted(LAYERS_BY_CODE)},
        )
    return layer


def check_filters(layer: SpatialLayer, filters: Mapping[str, Any]) -> None:
    """Every filter must exist on this layer, and enumerated values must be among the known ones."""
    _check_filters(filters, layer.all_filters, subject=layer.code, extra={"layer": layer.code})


def check_event_filters(filters: Mapping[str, Any]) -> None:
    _check_filters(filters, EVENTS.filters, subject="events")


def _check_filters(
    filters: Mapping[str, Any],
    available: tuple[ValueFilter, ...],
    *,
    subject: str,
    extra: dict[str, Any] | None = None,
) -> None:
    for name, value in filters.items():
        value_filter = next((f for f in available if f.name == name), None)
        if value_filter is None:
            raise UnsupportedFilterError(
                f"{subject} has no filter {name!r}",
                extensions={
                    **(extra or {}),
                    "filter": name,
                    "supportedFilters": [f.name for f in available],
                },
            )
        if value_filter.values and str(value) not in value_filter.values:
            raise UnsupportedFilterError(
                f"{name}={value!r} is not a value of {subject}.{value_filter.column}",
                extensions={**(extra or {}), "filter": name, "allowedValues": list(value_filter.values)},
            )


def check_name_search(layer: SpatialLayer, name_contains: str | None) -> None:
    if name_contains is not None and layer.name_column is None:
        raise UnsupportedFilterError(
            f"{layer.code} features have no name to search",
            extensions={"layer": layer.code, "filter": "nameContains"},
        )


def _check_release(layer: SpatialLayer, release_code: str | None) -> None:
    """Only reference layers come from a release; naming one for tenant data would be ignored silently."""
    if release_code is not None and layer.scope != "release":
        raise UnsupportedFilterError(
            f"{layer.code} is tenant data, which is not versioned by reference data release",
            extensions={"layer": layer.code, "filter": "refDataRelease"},
        )


def _scope_key(layer: SpatialLayer, tenant: TenantId | None) -> str | None:
    """What separates two result sets of the same layer: the tenant, for tenant data."""
    return tenant.value if layer.scope == "tenant" and tenant is not None else None


def _check_time_filter(layer: SpatialLayer, at: datetime | None) -> None:
    if at is not None and layer.period_column is None:
        raise UnsupportedFilterError(
            f"{layer.code} features have no validity period, so 'at' does not apply",
            extensions={"layer": layer.code, "filter": "at"},
        )


class ExportTooLargeError(GisValidationError):
    """An export is one complete file: a selection larger than the limit is refused, never cut short."""

    code = "export_too_large"
    title = "Export is larger than allowed"


class ExportNotPermittedError(PermissionDeniedError):
    """A source's licence does not let its data leave the platform (``redistribution_allowed`` false)."""

    code = "export_not_permitted"
    title = "The licence of this data does not permit exports"


class SpatialQueryService:
    """Reads reference and operational data; writes nothing but its own audit entries.

    Every method takes the caller's :class:`~app.core.access.Access`. Tenant data is read with the
    access's tenant set for row-level security; searches, reads of tenant data and exports are recorded
    in the audit log inside the same transaction (``app.services.audit_policy``).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        service_area: ServiceArea,
        limits: GeoContextLimits | None = None,
        clock: Clock = _utc_now,
        export_max_features: int = DEFAULT_EXPORT_MAX_FEATURES,
    ) -> None:
        self._session_factory = session_factory
        self._service_area = service_area
        self._limits = limits or GeoContextLimits()
        self._clock = clock
        self._export_max_features = export_max_features

    # --- catalogue -------------------------------------------------------------------------------

    async def catalogue(self) -> LayerCatalogue:
        """The published layers and what this API can do with each of them."""
        async with transaction(self._session_factory) as session:
            repository = SpatialQueryRepository(session)
            rows = await repository.layers()
            release = await repository.release(None)
            terms = () if release is None else await repository.dataset_terms(release.id)
        return LayerCatalogue(
            layers=[_layer_summary(row, terms) for row in rows],
            ref_data_release=None if release is None else release.code,
            attribution=merge_attribution(item.attribution for item in terms),
        )

    # --- features of one layer -------------------------------------------------------------------

    async def features(self, code: str, params: FeatureListQuery, access: Access) -> FeatureCollectionOut:
        layer, filters, bbox = self._selection(code, params)
        async with self._scoped(layer, access, params.ref_data_release) as (session, release):
            fingerprint = query_fingerprint(
                "features",
                layer.code,
                _release_id(release),
                _scope_key(layer, access.tenant),
                bbox,
                filters,
                params.name_contains,
                params.at,
            )
            cursor = cursor_of(params.cursor, fingerprint=fingerprint)
            at = self._period_instant(layer, params.at, cursor)
            rows = await SpatialQueryRepository(session).features(
                FeatureQuery(
                    layer=layer,
                    limit=fetch_limit(params.limit),
                    release_id=_release_id(release),
                    bbox=bbox,
                    filters=filters,
                    name_contains=params.name_contains,
                    at=at,
                    include_geometry=params.include_geometry,
                    after_id=None if cursor is None else cursor.identifier("id"),
                )
            )
            page = build_page(rows, limit=params.limit, fingerprint=fingerprint, key_of=_key_of(_by_id, at))
            record = audit_policy.feature_read(
                layer, params, bbox, at, release, page.count, continued=cursor is not None
            )
            if record is not None:
                await AuditRepository(session).record(record)
        return _collection(page, layer, release)

    async def export_features(
        self, code: str, params: FeatureExportQuery, access: Access
    ) -> FeatureExportOut:
        """The whole selection as one file, or 422 ``export_too_large``; always audited."""
        layer, filters, bbox = self._selection(code, params)
        async with self._scoped(layer, access, params.ref_data_release) as (session, release):
            terms: tuple[DatasetTerms, ...] = ()
            if release is not None:
                terms = tuple(
                    item
                    for item in await SpatialQueryRepository(session).dataset_terms(release.id)
                    if item.layer == layer.code
                )
                restricted = sorted({item.source for item in terms if not item.redistribution_allowed})
                if restricted:
                    raise ExportNotPermittedError(
                        f"the licence of {', '.join(restricted)} does not allow {layer.code} to leave the "
                        "platform",
                        extensions={
                            "layer": layer.code,
                            "sources": restricted,
                            "refDataRelease": release.code,
                        },
                    )
            at = self._period_instant(layer, params.at, None)
            rows = await SpatialQueryRepository(session).features(
                FeatureQuery(
                    layer=layer,
                    limit=self._export_max_features + 1,
                    release_id=_release_id(release),
                    bbox=bbox,
                    filters=filters,
                    name_contains=params.name_contains,
                    at=at,
                    include_geometry=True,
                )
            )
            self._check_export_size(len(rows), layer.code)
            await AuditRepository(session).record(
                audit_policy.feature_export(layer, params, bbox, at, release, len(rows))
            )
        return FeatureExportOut(
            features=[_feature(row) for row in rows],
            count=len(rows),
            layer=layer.code,
            ref_data_release=None if release is None else release.code,
            exported_at=self._clock(),
            tenant_id=None if layer.scope != "tenant" or access.tenant is None else access.tenant.value,
            attribution=merge_attribution(item.attribution for item in terms),
        )

    # --- spatial questions -----------------------------------------------------------------------

    async def within_distance(self, query: WithinDistanceQuery, access: Access) -> FeatureCollectionOut:
        layer, geometry = self._prepare(query)
        async with self._scoped(layer, access, query.ref_data_release) as (session, release):
            filters = query.filters.as_mapping()
            fingerprint = query_fingerprint(
                "within-distance",
                layer.code,
                _release_id(release),
                _scope_key(layer, access.tenant),
                geometry.wkb(),
                query.distance_m,
                filters,
                query.name_contains,
                query.at,
            )
            cursor = cursor_of(query.cursor, fingerprint=fingerprint)
            at = self._period_instant(layer, query.at, cursor)
            rows = await SpatialQueryRepository(session).within_distance(
                DistanceQuery(
                    layer=layer,
                    limit=fetch_limit(query.limit),
                    geometry_wkb=geometry.wkb(),
                    distance_m=query.distance_m,
                    release_id=_release_id(release),
                    filters=filters,
                    name_contains=query.name_contains,
                    at=at,
                    include_geometry=query.include_geometry,
                    after_distance_m=None if cursor is None else cursor.number("d"),
                    after_id=None if cursor is None else cursor.identifier("id"),
                )
            )
            page = build_page(
                rows, limit=query.limit, fingerprint=fingerprint, key_of=_key_of(_by_distance, at)
            )
            await AuditRepository(session).record(
                audit_policy.spatial_question(
                    "query.within_distance",
                    layer,
                    query,
                    geometry.wkb(),
                    at,
                    release,
                    page.count,
                    continued=cursor is not None,
                    distanceM=query.distance_m,
                )
            )
        return _collection(page, layer, release)

    async def nearest(self, query: NearestQuery, access: Access) -> FeatureCollectionOut:
        layer, geometry = self._prepare(query)
        at = self._period_instant(layer, query.at, None)
        async with self._scoped(layer, access, query.ref_data_release) as (session, release):
            filters = query.filters.as_mapping()
            rows = await SpatialQueryRepository(session).within_distance(
                DistanceQuery(
                    layer=layer,
                    limit=query.limit,
                    geometry_wkb=geometry.wkb(),
                    distance_m=query.max_distance_m,
                    release_id=_release_id(release),
                    filters=filters,
                    name_contains=query.name_contains,
                    at=at,
                    include_geometry=query.include_geometry,
                )
            )
            await AuditRepository(session).record(
                audit_policy.spatial_question(
                    "query.nearest",
                    layer,
                    query,
                    geometry.wkb(),
                    at,
                    release,
                    len(rows),
                    continued=False,
                    maxDistanceM=query.max_distance_m,
                    limit=query.limit,
                )
            )
        return _collection(Page(items=tuple(rows), next_cursor=None), layer, release)

    async def contains(self, query: ContainsQuery, access: Access) -> FeatureCollectionOut:
        layer, geometry = self._prepare(query)
        if not layer.areal:
            raise UnsupportedQueryError(
                f"{layer.code} has no areas, so it cannot contain a geometry",
                extensions={"layer": layer.code, "capabilities": list(layer.capabilities)},
            )
        async with self._scoped(layer, access, query.ref_data_release) as (session, release):
            filters = query.filters.as_mapping()
            fingerprint = query_fingerprint(
                "contains",
                layer.code,
                _release_id(release),
                _scope_key(layer, access.tenant),
                geometry.wkb(),
                query.mode,
                filters,
                query.name_contains,
                query.at,
            )
            cursor = cursor_of(query.cursor, fingerprint=fingerprint)
            at = self._period_instant(layer, query.at, cursor)
            rows = await SpatialQueryRepository(session).containing(
                ContainmentQuery(
                    layer=layer,
                    limit=fetch_limit(query.limit),
                    geometry_wkb=geometry.wkb(),
                    covers=query.mode == "covers",
                    release_id=_release_id(release),
                    filters=filters,
                    name_contains=query.name_contains,
                    at=at,
                    include_geometry=query.include_geometry,
                    after_id=None if cursor is None else cursor.identifier("id"),
                )
            )
            page = build_page(rows, limit=query.limit, fingerprint=fingerprint, key_of=_key_of(_by_id, at))
            await AuditRepository(session).record(
                audit_policy.spatial_question(
                    "query.contains",
                    layer,
                    query,
                    geometry.wkb(),
                    at,
                    release,
                    page.count,
                    continued=cursor is not None,
                    mode=query.mode,
                )
            )
        return _collection(page, layer, release)

    # --- reverse geocoding -----------------------------------------------------------------------

    async def reverse_geocode(
        self, lon: float, lat: float, access: Access, release_code: str | None = None
    ) -> ReverseGeocodeOut:
        """Where a position is: administrative hierarchy, nearest settlement and nearest road.

        Reference data only: the answer does not depend on any tenant's data. The question is recorded
        in the audit log like any other search, with the position reduced to its coarse extent.
        """
        point = parse_geojson_geometry(
            {"type": "Point", "coordinates": [lon, lat]},
            area=self._service_area,
            allowed_types=POINT_TYPES,
        )
        limits = self._limits
        async with access_transaction(self._session_factory, access) as session:
            repository = SpatialQueryRepository(session)
            release = require_usable_release(await repository.release(release_code), release_code)
            row = await repository.reverse(
                point.wkb(),
                release.id,
                settlement_radius_m=limits.settlement_radius_m,
                road_radius_m=limits.road_radius_m,
            )
            await AuditRepository(session).record(audit_policy.reverse_geocode(point.wkb(), release.code))
        return ReverseGeocodeOut(
            point=GeoJsonGeometry.from_shapely(point.geometry),
            admin=build_admin_hierarchy(row.admin_areas),
            nearest_settlement=nearest_settlement_of(row.settlement),
            nearest_road=nearest_road_of(row.road),
            settlement_radius_m=limits.settlement_radius_m,
            road_radius_m=limits.road_radius_m,
            missing_layers=list(row.missing_layers),
            ref_data_release=release.code,
            computed_at=self._clock(),
        )

    # --- events ----------------------------------------------------------------------------------

    async def events(self, params: EventListQuery, access: Access) -> EventCollectionOut:
        tenant = access.required_tenant(_EVENTS_NEED_A_TENANT)
        filters = params.as_mapping()
        check_event_filters(filters)
        bbox = None if params.bbox is None else parse_bbox(params.bbox, self._service_area)
        fingerprint = query_fingerprint(
            "events",
            tenant.value,
            params.time_from,
            params.time_to,
            bbox,
            filters,
            params.geofence_id,
            params.admin_area_id,
            params.admin_area_code,
        )
        cursor = cursor_of(params.cursor, fingerprint=fingerprint)
        window = self._window(params, cursor)
        async with access_transaction(self._session_factory, access) as session:
            rows = await SpatialQueryRepository(session).events(
                self._event_query(params, window, bbox, filters, fetch_limit(params.limit), cursor)
            )
            page = build_page(rows, limit=params.limit, fingerprint=fingerprint, key_of=_key_of_event(window))
            await AuditRepository(session).record(
                audit_policy.event_read(params, window, bbox, page.count, continued=cursor is not None)
            )
        return EventCollectionOut(
            features=[_event_feature(row) for row in page.items],
            count=page.count,
            layer=EVENT_LAYER,
            next_cursor=page.next_cursor,
            window=window,
        )

    async def export_events(self, params: EventExportQuery, access: Access) -> EventExportOut:
        """Every event of the window as one file, or 422 ``export_too_large``; always audited."""
        tenant = access.required_tenant(_EVENTS_NEED_A_TENANT)
        filters = params.as_mapping()
        check_event_filters(filters)
        bbox = None if params.bbox is None else parse_bbox(params.bbox, self._service_area)
        window = self._window(params, None)
        async with access_transaction(self._session_factory, access) as session:
            rows = await SpatialQueryRepository(session).events(
                self._event_query(params, window, bbox, filters, self._export_max_features + 1, None)
            )
            self._check_export_size(len(rows), EVENT_LAYER)
            await AuditRepository(session).record(audit_policy.event_export(params, window, bbox, len(rows)))
        return EventExportOut(
            features=[_event_feature(row) for row in rows],
            count=len(rows),
            layer=EVENT_LAYER,
            window=window,
            exported_at=self._clock(),
            tenant_id=tenant.value,
        )

    # --- helpers ---------------------------------------------------------------------------------

    def _selection(
        self, code: str, params: FeatureSelection
    ) -> tuple[SpatialLayer, dict[str, Any], Bbox | None]:
        layer = resolve_layer(code)
        filters = params.as_mapping()
        check_filters(layer, filters)
        check_name_search(layer, params.name_contains)
        _check_time_filter(layer, params.at)
        _check_release(layer, params.ref_data_release)
        bbox = None if params.bbox is None else parse_bbox(params.bbox, self._service_area)
        return layer, filters, bbox

    def _check_export_size(self, rows: int, what: str) -> None:
        if rows > self._export_max_features:
            raise ExportTooLargeError(
                f"the selection holds more than {self._export_max_features} features; narrow the area, "
                "the filters or the window and export again",
                extensions={"layer": what, "maxFeatures": self._export_max_features},
            )

    @staticmethod
    def _event_query(
        params: EventSelection,
        window: EventQueryWindow,
        bbox: Bbox | None,
        filters: Mapping[str, Any],
        limit: int,
        cursor: CursorValues | None,
    ) -> EventQuery:
        return EventQuery(
            time_from=window.time_from,
            time_to=window.time_to,
            limit=limit,
            bbox=bbox,
            filters=filters,
            geofence_id=params.geofence_id,
            admin_area_id=params.admin_area_id,
            admin_area_code=params.admin_area_code,
            include_geometry=getattr(params, "include_geometry", True),
            after_observed_at=None if cursor is None else cursor.instant("t"),
            after_event_id=None if cursor is None else cursor.text("e"),
        )

    def _prepare(self, query: SpatialQuery) -> tuple[SpatialLayer, ValidatedGeometry]:
        """The layer and the validated geometry of a spatial query."""
        layer = resolve_layer(query.target)
        filters = query.filters.as_mapping()
        check_filters(layer, filters)
        check_name_search(layer, query.name_contains)
        _check_time_filter(layer, query.at)
        _check_release(layer, query.ref_data_release)
        geometry = parse_geojson_geometry(query.geometry.as_mapping(), area=self._service_area)
        return layer, geometry

    def _period_instant(
        self, layer: SpatialLayer, at: datetime | None, cursor: CursorValues | None
    ) -> datetime | None:
        """Layers with a validity period are read as of an instant; by default, now.

        Later pages take that instant from the cursor, so paging sees one state of the layer instead of a
        slightly different one per page - and so the cursor still belongs to the same query.
        """
        if layer.period_column is None:
            return None
        if at is not None:
            return at
        return self._clock() if cursor is None else cursor.instant("at")

    def _window(self, params: EventSelection, cursor: CursorValues | None) -> EventQueryWindow:
        """The window to read, defaulting to the last day.

        A later page reads the window its cursor carries, so a default window does not drift while a
        client pages through it. A window is bounded whatever it came from: the cursor is not a
        capability, and its values are checked like any other input.
        """
        if cursor is not None:
            return self._checked_window(cursor.instant("wf"), cursor.instant("wt"))
        time_to = params.time_to or self._clock()
        return self._checked_window(
            params.time_from or time_to - timedelta(hours=EVENT_DEFAULT_WINDOW_HOURS), time_to
        )

    @staticmethod
    def _checked_window(time_from: datetime, time_to: datetime) -> EventQueryWindow:
        if time_to < time_from:
            raise GisValidationError("'to' must not be before 'from'")
        if time_to - time_from > EVENT_MAX_WINDOW:
            raise TimeWindowError(
                f"the window must not be longer than {EVENT_MAX_WINDOW_DAYS} days; ask for one window per "
                "period, or page through with the cursor",
                extensions={"maxWindowDays": EVENT_MAX_WINDOW_DAYS},
            )
        return EventQueryWindow(time_from=time_from, time_to=time_to)

    @asynccontextmanager
    async def _scoped(
        self, layer: SpatialLayer, access: Access, release_code: str | None
    ) -> AsyncIterator[tuple[AsyncSession, ReleaseRow | None]]:
        """A transaction acting for ``access``, and the release the layer's features come from.

        Operational layers need the tenant, so row-level security decides what is visible, and have no
        release. Reference layers resolve the release first; the tenant, when there is one, is still set
        so that the audit entry names it.
        """
        if layer.scope == "tenant":
            access.required_tenant(
                f"{layer.code} is tenant data; name the tenant in tenantId",
                {"layer": layer.code},
            )
            async with access_transaction(self._session_factory, access) as session:
                yield session, None
            return
        async with access_transaction(self._session_factory, access) as session:
            release = await SpatialQueryRepository(session).release(release_code)
            yield session, require_usable_release(release, release_code)


# --- assembling answers ----------------------------------------------------------------------------------


def _release_id(release: ReleaseRow | None) -> uuid.UUID | None:
    return None if release is None else release.id


def _key_of(base: Callable[[Any], dict[str, Any]], at: datetime | None) -> Callable[[Any], dict[str, Any]]:
    """The cursor key, with the instant a time-filtered layer was read at."""
    if at is None:
        return base
    return lambda row: {**base(row), "at": at.isoformat()}


def _by_id(row: FeatureRow) -> dict[str, Any]:
    return {"id": str(row.id)}


def _by_distance(row: FeatureRow) -> dict[str, Any]:
    return {"d": row.distance_m, "id": str(row.id)}


def _key_of_event(window: EventQueryWindow) -> Callable[[EventRow], dict[str, Any]]:
    """The cursor key of an event page, with the window the page was read from."""

    def key(row: EventRow) -> dict[str, Any]:
        return {
            "t": row.observed_at.isoformat(),
            "e": row.event_id,
            "wf": window.time_from.isoformat(),
            "wt": window.time_to.isoformat(),
        }

    return key


def _feature(row: FeatureRow) -> FeatureOut:
    properties = dict(row.properties)
    if row.distance_m is not None:
        properties["distanceM"] = metres(row.distance_m)
    if row.relation is not None:
        properties["relation"] = row.relation
    return FeatureOut(id=str(row.id), geometry=row.geometry, properties=properties)


def _event_feature(row: EventRow) -> FeatureOut:
    return FeatureOut(id=row.event_id, geometry=row.geometry, properties=dict(row.properties))


def _collection(
    page: Page[FeatureRow], layer: SpatialLayer, release: ReleaseRow | None
) -> FeatureCollectionOut:
    return FeatureCollectionOut(
        features=[_feature(row) for row in page.items],
        count=page.count,
        layer=layer.code,
        next_cursor=page.next_cursor,
        ref_data_release=None if release is None else release.code,
    )


def _layer_summary(row: LayerRow, terms: Sequence[DatasetTerms] = ()) -> LayerSummary:
    layer = LAYERS_BY_CODE.get(row.code)
    own = [item for item in terms if item.layer == row.code]
    return LayerSummary(
        code=row.code,
        name=row.name,
        description=row.description,
        layer_group=row.layer_group,
        geometry_types=list(row.geometry_types),
        srid=row.srid,
        metric_srid=row.metric_srid,
        tenant_scoped=row.tenant_scoped,
        default_sharing_policy=row.default_sharing_policy,
        update_frequency=row.update_frequency,
        nominal_accuracy_m=row.nominal_accuracy_m,
        queryable=layer is not None,
        capabilities=[] if layer is None else list(layer.capabilities),
        filters=[] if layer is None else [f.name for f in layer.all_filters],
        properties=[] if layer is None else list(layer.property_keys),
        time_filtered=layer is not None and layer.period_column is not None,
        attribution=merge_attribution(item.attribution for item in own),
        exportable=all(item.redistribution_allowed for item in own),
    )
