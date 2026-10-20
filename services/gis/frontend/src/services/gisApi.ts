/**
 * The GIS Core Service API, as the map client uses it.
 *
 * One function per endpoint, each validating its answer. Every spatial question the client asks is a
 * geographic one - what is here, what is near here, what contains this, what was observed where; the
 * service has no notion of people or messages, and neither has this module (ADR-0012).
 *
 * `createGisApi` returns the interface a host application can replace, which is what lets the map be
 * embedded against a different transport (a gateway, a test double) without touching the components.
 */
import type { Bounds } from '../geo/geometry';
import { boundsToParameter } from '../geo/geometry';
import type {
  DevicePlacement,
  EventCollection,
  EventExport,
  FeatureCollection,
  FeatureExport,
  Geofence,
  GeofenceList,
  Geometry,
  Identity,
  LayerCatalogue,
  Liveness,
  Readiness,
  ReverseGeocode,
  ServiceArea,
  Site,
  SiteList,
} from '../types/api';
import {
  devicePlacementSchema,
  eventCollectionSchema,
  eventExportSchema,
  featureCollectionSchema,
  featureExportSchema,
  geofenceListSchema,
  geofenceSchema,
  identitySchema,
  layerCatalogueSchema,
  livenessSchema,
  readinessSchema,
  reverseGeocodeSchema,
  serviceAreaSchema,
  siteListSchema,
  siteSchema,
} from '../types/api';
import { ApiClient, type ClientOptions, type QueryValue } from './apiClient';

/** Attribute filters, keyed as `GET /geo/v1/layers` names them (`type`, `status`, `level`, ...). */
export type LayerFilters = Readonly<Record<string, QueryValue>>;

export interface CallOptions {
  readonly signal?: AbortSignal;
}

export interface FeatureQuery {
  readonly layer: string;
  readonly bounds?: Bounds | null;
  readonly filters?: LayerFilters;
  readonly nameContains?: string | null;
  /** Instant a time-filtered layer must be valid at (ISO 8601). */
  readonly at?: string | null;
  readonly refDataRelease?: string | null;
  readonly tenantId?: string | null;
  readonly includeGeometry?: boolean;
  readonly limit?: number;
  readonly cursor?: string | null;
}

/** What to export from a layer: the selection of `FeatureQuery`, without paging. */
export type FeatureExportQuery = Omit<FeatureQuery, 'includeGeometry' | 'limit' | 'cursor'>;

export interface EventQuery {
  readonly from?: string | null;
  readonly to?: string | null;
  readonly bounds?: Bounds | null;
  readonly eventType?: string | null;
  readonly eventSubtype?: string | null;
  readonly sourceType?: string | null;
  readonly deviceId?: string | null;
  readonly geofenceId?: string | null;
  readonly adminAreaId?: string | null;
  readonly adminAreaCode?: string | null;
  readonly tenantId?: string | null;
  readonly includeGeometry?: boolean;
  readonly limit?: number;
  readonly cursor?: string | null;
}

interface SpatialQueryBase {
  readonly target: string;
  readonly geometry: Geometry;
  readonly filters?: LayerFilters;
  readonly nameContains?: string | null;
  readonly at?: string | null;
  readonly refDataRelease?: string | null;
  readonly includeGeometry?: boolean;
  readonly tenantId?: string | null;
}

export interface WithinDistanceQuery extends SpatialQueryBase {
  readonly distanceM: number;
  readonly limit?: number;
  readonly cursor?: string | null;
}

export interface NearestQuery extends SpatialQueryBase {
  readonly maxDistanceM?: number;
  readonly limit?: number;
}

export interface ContainsQuery extends SpatialQueryBase {
  readonly mode?: 'covers' | 'intersects';
  readonly limit?: number;
  readonly cursor?: string | null;
}

export interface GeofenceListQuery {
  readonly status?: string | null;
  readonly kind?: string | null;
  readonly nameContains?: string | null;
  readonly bounds?: Bounds | null;
  readonly at?: string | null;
  readonly ownedOnly?: boolean;
  readonly tenantId?: string | null;
  readonly limit?: number;
  readonly cursor?: string | null;
}

export interface SiteListQuery {
  readonly status?: string | null;
  readonly siteType?: string | null;
  readonly nameContains?: string | null;
  readonly bounds?: Bounds | null;
  readonly tenantId?: string | null;
  readonly limit?: number;
  readonly cursor?: string | null;
}

/** A geofence to create or replace. `version` makes a replace conditional on what was read. */
export interface GeofenceInput {
  readonly name: string;
  readonly description?: string | null;
  readonly externalId?: string | null;
  readonly definition: {
    readonly kind: string;
    readonly geometry: Geometry;
    readonly radiusM?: number | null;
  };
  readonly status?: string;
  readonly effectiveDuring?: { readonly from?: string | null; readonly to?: string | null };
  readonly sharingPolicy?: string;
  readonly sharedWithTenants?: readonly string[];
  readonly attributes?: Readonly<Record<string, unknown>>;
  readonly version?: number;
}

export interface DeleteGeofenceOptions extends CallOptions {
  readonly tenantId?: string | null;
  readonly purge?: boolean;
  readonly version?: number | null;
}

/** What to export of the events: the selection of `EventQuery`, without paging. */
export type EventExportQuery = Omit<EventQuery, 'includeGeometry' | 'limit' | 'cursor'>;

export interface GisApi {
  getLiveness(options?: CallOptions): Promise<Liveness>;
  /** What the caller may do and the tenant it acts for. */
  getIdentity(options?: CallOptions): Promise<Identity>;
  getReadiness(options?: CallOptions): Promise<Readiness>;
  getServiceArea(options?: CallOptions): Promise<ServiceArea>;
  getLayerCatalogue(options?: CallOptions & { tenantId?: string | null }): Promise<LayerCatalogue>;
  listFeatures(query: FeatureQuery, options?: CallOptions): Promise<FeatureCollection>;
  listEvents(query: EventQuery, options?: CallOptions): Promise<EventCollection>;
  queryWithinDistance(query: WithinDistanceQuery, options?: CallOptions): Promise<FeatureCollection>;
  queryNearest(query: NearestQuery, options?: CallOptions): Promise<FeatureCollection>;
  queryContains(query: ContainsQuery, options?: CallOptions): Promise<FeatureCollection>;
  reverseGeocode(
    position: readonly [number, number],
    options?: CallOptions & { refDataRelease?: string | null },
  ): Promise<ReverseGeocode>;
  listGeofences(query: GeofenceListQuery, options?: CallOptions): Promise<GeofenceList>;
  getGeofence(id: string, options?: CallOptions & { tenantId?: string | null }): Promise<Geofence>;
  createGeofence(
    geofence: GeofenceInput,
    options?: CallOptions & { tenantId?: string | null },
  ): Promise<Geofence>;
  replaceGeofence(
    id: string,
    geofence: GeofenceInput & { readonly version: number },
    options?: CallOptions & { tenantId?: string | null },
  ): Promise<Geofence>;
  deleteGeofence(id: string, options?: DeleteGeofenceOptions): Promise<void>;
  listSites(query: SiteListQuery, options?: CallOptions): Promise<SiteList>;
  getSite(id: string, options?: CallOptions & { tenantId?: string | null }): Promise<Site>;
  getDevicePlacement(
    id: string,
    options?: CallOptions & { tenantId?: string | null; at?: string | null },
  ): Promise<DevicePlacement>;
  /** The whole selection of a layer as one GeoJSON document (refused, not cut short, when too large). */
  exportFeatures(query: FeatureExportQuery, options?: CallOptions): Promise<FeatureExport>;
  exportEvents(query: EventExportQuery, options?: CallOptions): Promise<EventExport>;
}

function featureSelection(query: FeatureExportQuery): Record<string, QueryValue> {
  return {
    ...definedFilters(query.filters),
    bbox: bbox(query.bounds),
    nameContains: query.nameContains ?? undefined,
    at: query.at ?? undefined,
    refDataRelease: query.refDataRelease ?? undefined,
    tenantId: query.tenantId ?? undefined,
  };
}

function eventSelection(query: EventExportQuery): Record<string, QueryValue> {
  return {
    from: query.from ?? undefined,
    to: query.to ?? undefined,
    bbox: bbox(query.bounds),
    eventType: query.eventType ?? undefined,
    eventSubtype: query.eventSubtype ?? undefined,
    sourceType: query.sourceType ?? undefined,
    deviceId: query.deviceId ?? undefined,
    geofenceId: query.geofenceId ?? undefined,
    adminAreaId: query.adminAreaId ?? undefined,
    adminAreaCode: query.adminAreaCode ?? undefined,
    tenantId: query.tenantId ?? undefined,
  };
}

function bbox(bounds: Bounds | null | undefined): string | undefined {
  return bounds === null || bounds === undefined ? undefined : boundsToParameter(bounds);
}

/** Only the filters that were set, so an unset filter is not sent at all. */
function definedFilters(filters: LayerFilters | undefined): Record<string, QueryValue> {
  const result: Record<string, QueryValue> = {};
  for (const [name, value] of Object.entries(filters ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      result[name] = value;
    }
  }
  return result;
}

function spatialBody(query: SpatialQueryBase): Record<string, unknown> {
  const filters = definedFilters(query.filters);
  return {
    target: query.target,
    geometry: query.geometry,
    ...(Object.keys(filters).length > 0 ? { filters } : {}),
    ...(query.nameContains ? { nameContains: query.nameContains } : {}),
    ...(query.at ? { at: query.at } : {}),
    ...(query.refDataRelease ? { refDataRelease: query.refDataRelease } : {}),
    ...(query.includeGeometry === undefined ? {} : { includeGeometry: query.includeGeometry }),
  };
}

export function createGisApi(options: ClientOptions = {}): GisApi {
  const client = new ApiClient(options);

  return {
    getLiveness: (call = {}) => client.get('/health/live', livenessSchema, call),

    getIdentity: (call = {}) => client.get('/geo/v1/me', identitySchema, call),

    // Readiness answers 503 with a full report when the service is not ready; both are valid data.
    getReadiness: (call = {}) =>
      client.get('/health/ready', readinessSchema, { ...call, acceptStatuses: [200, 503] }),

    getServiceArea: (call = {}) => client.get('/geo/v1/service-area', serviceAreaSchema, call),

    getLayerCatalogue: ({ tenantId, ...call } = {}) =>
      client.get('/geo/v1/layers', layerCatalogueSchema, {
        ...call,
        query: { tenantId: tenantId ?? undefined },
      }),

    listFeatures: (query, call = {}) =>
      client.get(
        `/geo/v1/layers/${encodeURIComponent(query.layer)}/features`,
        featureCollectionSchema,
        {
          ...call,
          query: {
            ...featureSelection(query),
            includeGeometry: query.includeGeometry ?? undefined,
            limit: query.limit ?? undefined,
            cursor: query.cursor ?? undefined,
          },
        },
      ),

    listEvents: (query, call = {}) =>
      client.get('/geo/v1/events', eventCollectionSchema, {
        ...call,
        query: {
          ...eventSelection(query),
          includeGeometry: query.includeGeometry ?? undefined,
          limit: query.limit ?? undefined,
          cursor: query.cursor ?? undefined,
        },
      }),

    queryWithinDistance: async (query, call = {}) => {
      const response = await client.post(
        '/geo/v1/query/within-distance',
        {
          ...spatialBody(query),
          distanceM: query.distanceM,
          ...(query.limit === undefined ? {} : { limit: query.limit }),
          ...(query.cursor ? { cursor: query.cursor } : {}),
        },
        featureCollectionSchema,
        { ...call, query: { tenantId: query.tenantId ?? undefined }, acceptStatuses: [200] },
      );
      return response.data;
    },

    queryNearest: async (query, call = {}) => {
      const response = await client.post(
        '/geo/v1/query/nearest',
        {
          ...spatialBody(query),
          ...(query.maxDistanceM === undefined ? {} : { maxDistanceM: query.maxDistanceM }),
          ...(query.limit === undefined ? {} : { limit: query.limit }),
        },
        featureCollectionSchema,
        { ...call, query: { tenantId: query.tenantId ?? undefined }, acceptStatuses: [200] },
      );
      return response.data;
    },

    queryContains: async (query, call = {}) => {
      const response = await client.post(
        '/geo/v1/query/contains',
        {
          ...spatialBody(query),
          ...(query.mode === undefined ? {} : { mode: query.mode }),
          ...(query.limit === undefined ? {} : { limit: query.limit }),
          ...(query.cursor ? { cursor: query.cursor } : {}),
        },
        featureCollectionSchema,
        { ...call, query: { tenantId: query.tenantId ?? undefined }, acceptStatuses: [200] },
      );
      return response.data;
    },

    reverseGeocode: ([lon, lat], { refDataRelease, ...call } = {}) =>
      client.get('/geo/v1/reverse', reverseGeocodeSchema, {
        ...call,
        query: { lon, lat, refDataRelease: refDataRelease ?? undefined },
      }),

    listGeofences: (query, call = {}) =>
      client.get('/geo/v1/geofences', geofenceListSchema, {
        ...call,
        query: {
          status: query.status ?? undefined,
          kind: query.kind ?? undefined,
          nameContains: query.nameContains ?? undefined,
          bbox: bbox(query.bounds),
          at: query.at ?? undefined,
          ownedOnly: query.ownedOnly ?? undefined,
          tenantId: query.tenantId ?? undefined,
          limit: query.limit ?? undefined,
          cursor: query.cursor ?? undefined,
        },
      }),

    getGeofence: (id, { tenantId, ...call } = {}) =>
      client.get(`/geo/v1/geofences/${encodeURIComponent(id)}`, geofenceSchema, {
        ...call,
        query: { tenantId: tenantId ?? undefined },
      }),

    createGeofence: async (geofence, { tenantId, ...call } = {}) => {
      const response = await client.post('/geo/v1/geofences', geofence, geofenceSchema, {
        ...call,
        query: { tenantId: tenantId ?? undefined },
        acceptStatuses: [201],
      });
      return response.data;
    },

    replaceGeofence: async (id, geofence, { tenantId, ...call } = {}) => {
      const response = await client.put(
        `/geo/v1/geofences/${encodeURIComponent(id)}`,
        geofence,
        geofenceSchema,
        { ...call, query: { tenantId: tenantId ?? undefined }, acceptStatuses: [200] },
      );
      return response.data;
    },

    deleteGeofence: (id, { tenantId, purge, version, ...call } = {}) =>
      client.delete(`/geo/v1/geofences/${encodeURIComponent(id)}`, {
        ...call,
        query: {
          tenantId: tenantId ?? undefined,
          purge: purge ?? undefined,
          version: version ?? undefined,
        },
      }),

    listSites: (query, call = {}) =>
      client.get('/geo/v1/sites', siteListSchema, {
        ...call,
        query: {
          status: query.status ?? undefined,
          siteType: query.siteType ?? undefined,
          nameContains: query.nameContains ?? undefined,
          bbox: bbox(query.bounds),
          tenantId: query.tenantId ?? undefined,
          limit: query.limit ?? undefined,
          cursor: query.cursor ?? undefined,
        },
      }),

    getSite: (id, { tenantId, ...call } = {}) =>
      client.get(`/geo/v1/sites/${encodeURIComponent(id)}`, siteSchema, {
        ...call,
        query: { tenantId: tenantId ?? undefined },
      }),

    getDevicePlacement: (id, { tenantId, at, ...call } = {}) =>
      client.get(`/geo/v1/devices/${encodeURIComponent(id)}/placement`, devicePlacementSchema, {
        ...call,
        query: { tenantId: tenantId ?? undefined, at: at ?? undefined },
      }),

    exportFeatures: (query, call = {}) =>
      client.get(`/geo/v1/layers/${encodeURIComponent(query.layer)}/export`, featureExportSchema, {
        ...call,
        query: featureSelection(query),
      }),

    exportEvents: (query, call = {}) =>
      client.get('/geo/v1/events/export', eventExportSchema, { ...call, query: eventSelection(query) }),
  };
}

/** The client the application uses: configured from `VITE_*` (see `config.ts`). */
export const gisApi: GisApi = createGisApi();
