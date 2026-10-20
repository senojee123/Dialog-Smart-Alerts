/**
 * Fixtures for the client's tests.
 *
 * The shapes mirror the backend's response models (`backend/app/schemas`) and the examples in
 * `docs/api/spatial-queries.md`; the places are the ones the backend's own fixtures use, around
 * Habarana in the North Central Province.
 */
import type {
  ApiFeature,
  EventCollection,
  FeatureCollection,
  Geofence,
  Identity,
  LayerCatalogue,
  LayerSummary,
  Readiness,
  ReverseGeocode,
  ServiceArea,
} from '../types/api';

export const readyReport: Readiness = {
  status: 'ready',
  service: 'gis-core-service',
  version: '0.1.0',
  checks: [
    { name: 'database', status: 'pass', durationMs: 3.1, detail: { serverVersion: '18.6', database: 'gis' }, error: null },
    { name: 'postgis', status: 'pass', durationMs: 1.2, detail: { libVersion: '3.6.4' }, error: null },
    { name: 'spatial_reference_systems', status: 'pass', durationMs: 0.8, detail: { required: [3857, 4326, 5235], missing: [] }, error: null },
    { name: 'crs_consistency', status: 'warn', durationMs: 0.9, detail: { offsetM: 0.4 }, error: 'database and application disagree' },
    { name: 'migrations', status: 'pass', durationMs: 0.5, detail: { applied: ['20260917_0006'], expected: ['20260917_0006'] }, error: null },
  ],
};

export const serviceArea: ServiceArea = {
  type: 'Feature',
  geometry: {
    type: 'Polygon',
    coordinates: [
      [
        [79.44, 5.66],
        [82.15, 5.66],
        [82.15, 10.08],
        [79.44, 10.08],
        [79.44, 5.66],
      ],
    ],
  },
  properties: {
    bbox: [79.44, 5.66, 82.15, 10.08],
    crs: 'EPSG:4326',
    metricCrs: 'EPSG:5235',
    description: 'Positions outside this box are rejected.',
  },
};

export const settlementLayer: LayerSummary = {
  code: 'ref.settlement',
  name: 'Settlements',
  description: 'Cities, towns and villages as points or footprints.',
  layerGroup: 'reference',
  geometryTypes: ['POINT', 'MULTIPOLYGON'],
  srid: 4326,
  metricSrid: 5235,
  tenantScoped: false,
  defaultSharingPolicy: null,
  updateFrequency: 'quarterly',
  nominalAccuracyM: 100,
  queryable: true,
  capabilities: ['features', 'within_distance', 'nearest'],
  filters: ['type', 'adminAreaId'],
  properties: ['name', 'settlementType', 'population', 'basis'],
  timeFiltered: false,
  attribution: ['© OpenStreetMap contributors'],
  exportable: true,
};

export const deviceLayer: LayerSummary = {
  code: 'ops.device',
  name: 'Devices',
  description: 'Cameras and sensors a tenant operates.',
  layerGroup: 'operational',
  geometryTypes: ['POINT'],
  srid: 4326,
  metricSrid: 5235,
  tenantScoped: true,
  defaultSharingPolicy: 'private',
  updateFrequency: 'continuous',
  nominalAccuracyM: 5,
  queryable: true,
  capabilities: ['features', 'within_distance', 'nearest'],
  filters: ['type', 'status', 'siteId'],
  properties: ['name', 'deviceType', 'status', 'tenantId'],
  timeFiltered: false,
  attribution: [],
  exportable: true,
};

export const protectedAreaLayer: LayerSummary = {
  code: 'ref.protected_area',
  name: 'Protected areas',
  description: 'National parks, reserves and sanctuaries.',
  layerGroup: 'reference',
  geometryTypes: ['MULTIPOLYGON'],
  srid: 4326,
  metricSrid: 5235,
  tenantScoped: false,
  defaultSharingPolicy: null,
  updateFrequency: 'annual',
  nominalAccuracyM: 50,
  queryable: true,
  capabilities: ['features', 'within_distance', 'nearest', 'contains'],
  filters: ['type', 'managingAuthority'],
  properties: ['name', 'designation', 'managingAuthority'],
  timeFiltered: false,
  attribution: ['© OpenStreetMap contributors'],
  exportable: true,
};

export const geofenceLayer: LayerSummary = {
  code: 'ops.geofence',
  name: 'Geofences',
  description: 'Areas a tenant maintains.',
  layerGroup: 'operational',
  geometryTypes: ['MULTIPOLYGON'],
  srid: 4326,
  metricSrid: 5235,
  tenantScoped: true,
  defaultSharingPolicy: 'private',
  updateFrequency: 'continuous',
  nominalAccuracyM: null,
  queryable: true,
  capabilities: ['features', 'within_distance', 'nearest', 'contains'],
  filters: ['type', 'status'],
  properties: ['name', 'geofenceKind', 'status', 'radiusM', 'areaM2'],
  timeFiltered: true,
  attribution: [],
  exportable: true,
};

export const fieldOfViewLayer: LayerSummary = {
  code: 'ops.device_field_of_view',
  name: 'Fields of view',
  description: 'What each device observes.',
  layerGroup: 'operational',
  geometryTypes: ['MULTIPOLYGON'],
  srid: 4326,
  metricSrid: 5235,
  tenantScoped: true,
  defaultSharingPolicy: 'private',
  updateFrequency: 'continuous',
  nominalAccuracyM: null,
  queryable: true,
  capabilities: ['features', 'within_distance', 'nearest', 'contains'],
  filters: ['deviceId', 'geometryMethod'],
  properties: ['deviceId', 'geometryMethod', 'bearingDeg', 'fovDeg', 'rangeM'],
  timeFiltered: true,
  attribution: [],
  exportable: true,
};

export const adminAreaLayer: LayerSummary = {
  code: 'ref.admin_area',
  name: 'Administrative areas',
  description: 'Provinces, districts, DS and GN divisions.',
  layerGroup: 'reference',
  geometryTypes: ['MULTIPOLYGON'],
  srid: 4326,
  metricSrid: 5235,
  tenantScoped: false,
  defaultSharingPolicy: null,
  updateFrequency: 'annual',
  nominalAccuracyM: 25,
  queryable: true,
  capabilities: ['features', 'within_distance', 'nearest', 'contains'],
  filters: ['level', 'code', 'parentId'],
  properties: ['name', 'code', 'level', 'levelName'],
  timeFiltered: false,
  attribution: ['Survey Department of Sri Lanka; OCHA'],
  exportable: true,
};

export const roadLayer: LayerSummary = {
  code: 'ref.road',
  name: 'Roads',
  description: 'The road network by class.',
  layerGroup: 'reference',
  geometryTypes: ['MULTILINESTRING'],
  srid: 4326,
  metricSrid: 5235,
  tenantScoped: false,
  defaultSharingPolicy: null,
  updateFrequency: 'quarterly',
  nominalAccuracyM: 15,
  queryable: true,
  capabilities: ['features', 'within_distance', 'nearest'],
  filters: ['type', 'refCode'],
  properties: ['name', 'class', 'refCode'],
  timeFiltered: false,
  attribution: ['© OpenStreetMap contributors'],
  exportable: true,
};

export const waterBodyLayer: LayerSummary = {
  code: 'ref.water_body',
  name: 'Water',
  description: 'Tanks, lakes, rivers and canals.',
  layerGroup: 'reference',
  geometryTypes: ['MULTIPOLYGON', 'MULTILINESTRING'],
  srid: 4326,
  metricSrid: 5235,
  tenantScoped: false,
  defaultSharingPolicy: null,
  updateFrequency: 'quarterly',
  nominalAccuracyM: 30,
  queryable: true,
  capabilities: ['features', 'within_distance', 'nearest', 'contains'],
  filters: ['type'],
  properties: ['name', 'waterType'],
  timeFiltered: false,
  attribution: ['© OpenStreetMap contributors'],
  exportable: true,
};

/** What a deployment with the fixture reference data publishes. */
export const layerCatalogue: LayerCatalogue = {
  layers: [
    adminAreaLayer,
    settlementLayer,
    roadLayer,
    waterBodyLayer,
    protectedAreaLayer,
    geofenceLayer,
    fieldOfViewLayer,
    deviceLayer,
  ],
  refDataRelease: 'ref-2026.09-lka-open',
  attribution: ['Survey Department of Sri Lanka; OCHA', '© OpenStreetMap contributors'],
};

export const emptyFeatureCollection: FeatureCollection = {
  type: 'FeatureCollection',
  features: [],
  count: 0,
  layer: null,
  nextCursor: null,
  refDataRelease: null,
};

export const settlementFeature: ApiFeature = {
  type: 'Feature',
  id: '0199f3d2-0000-0000-0000-00000000aa01',
  geometry: { type: 'Point', coordinates: [80.7513, 8.0342] },
  properties: {
    name: 'Habarana',
    settlementType: 'town',
    population: 4200,
    basis: 'point',
  },
};

export const deviceFeature: ApiFeature = {
  type: 'Feature',
  id: '0199f3d2-0000-0000-0000-00000000bb01',
  geometry: { type: 'Point', coordinates: [80.752, 8.04] },
  properties: {
    name: 'HB-CAM-01',
    deviceType: 'camera',
    status: 'active',
    tenantId: 'wildlife-dept',
    mountingHeightM: 6.5,
  },
};

export const eventFeature: ApiFeature = {
  type: 'Feature',
  id: 'evt-2026-09-000123',
  geometry: { type: 'Point', coordinates: [80.749, 8.037] },
  properties: {
    eventId: 'evt-2026-09-000123',
    tenantId: 'wildlife-dept',
    observedAt: '2026-09-14T03:02:10Z',
    eventType: 'wildlife.elephant_detected',
    eventSubtype: null,
    sourceType: 'sensor',
    deviceId: '0199f3d2-0000-0000-0000-00000000bb01',
    locationSource: 'sensor',
    geometryKind: 'point',
    admin: { l1: 'LK7', l2: 'LK71', l3: null, l4: null },
    refDataRelease: 'ref-2026.09-lka-open',
  },
};

export function featureCollection(
  features: readonly ApiFeature[],
  extra: Partial<FeatureCollection> = {},
): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: [...features],
    count: features.length,
    layer: null,
    nextCursor: null,
    refDataRelease: 'ref-2026.09-lka-open',
    ...extra,
  };
}

export function eventCollection(
  features: readonly ApiFeature[],
  extra: Partial<EventCollection> = {},
): EventCollection {
  return {
    ...featureCollection(features),
    window: { from: '2026-09-14T00:00:00Z', to: '2026-09-15T00:00:00Z' },
    ...extra,
  };
}

export const reverseGeocode: ReverseGeocode = {
  point: { type: 'Point', coordinates: [80.7513, 8.0342] },
  admin: {
    province: {
      id: '0199f3d2-0000-0000-0000-0000000011a1',
      code: 'LK7',
      name: 'North Central Province',
      nameSi: null,
      nameTa: null,
      level: 1,
      levelName: 'province',
    },
    district: {
      id: '0199f3d2-0000-0000-0000-0000000011a2',
      code: 'LK71',
      name: 'Anuradhapura',
      nameSi: null,
      nameTa: null,
      level: 2,
      levelName: 'district',
    },
    dsDivision: null,
    gnDivision: null,
    codes: { l1: 'LK7', l2: 'LK71', l3: null, l4: null },
    onBoundary: false,
  },
  nearestSettlement: {
    id: '0199f3d2-0000-0000-0000-00000000aa01',
    name: 'Habarana',
    nameSi: null,
    nameTa: null,
    settlementType: 'town',
    basis: 'point',
    distanceM: 512.34,
  },
  nearestRoad: {
    id: '0199f3d2-0000-0000-0000-00000000cc01',
    name: 'Habarana - Trincomalee',
    class: 'A',
    refCode: 'A11',
    distanceM: 48.9,
  },
  settlementRadiusM: 25_000,
  roadRadiusM: 10_000,
  missingLayers: [],
  refDataRelease: 'ref-2026.09-lka-open',
  computedAt: '2026-09-21T09:15:04.221Z',
};

export const geofence: Geofence = {
  id: '0199f3d2-0000-0000-0000-00000000dd01',
  tenantId: 'wildlife-dept',
  name: 'Habarana junction watch zone',
  description: null,
  externalId: 'WZ-007',
  definition: {
    kind: 'circle',
    geometry: { type: 'Point', coordinates: [80.7487, 8.0356] },
    radiusM: 750,
  },
  areaM2: 1_767_145.87,
  status: 'active',
  effectiveDuring: { from: '2026-09-01T00:00:00Z', to: null },
  sharingPolicy: 'private',
  sharedWithTenants: [],
  attributes: {},
  version: 1,
  createdAt: '2026-09-01T00:00:00Z',
  updatedAt: '2026-09-01T00:00:00Z',
  createdBy: 'operator@wildlife-dept',
  updatedBy: null,
};

export const polygonGeofence: Geofence = {
  ...geofence,
  id: '0199f3d2-0000-0000-0000-00000000dd02',
  name: 'Elephant corridor watch',
  definition: {
    kind: 'polygon',
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [80.74, 8.02],
          [80.78, 8.02],
          [80.78, 8.05],
          [80.74, 8.05],
          [80.74, 8.02],
        ],
      ],
    },
    radiusM: null,
  },
  version: 3,
};

/** The caller as the GIS answers every request from the platform: every panel is offered. */
export const administrator: Identity = {
  subject: 'platform',
  clientId: null,
  permissions: [
    'map:read',
    'query:spatial',
    'events:read',
    'geofences:write',
    'assets:write',
    'data:purge',
    'data:export',
    'audit:read',
    'events:enrich',
  ],
  tenants: ['wildlife-dept'],
  allTenants: false,
  defaultTenant: 'wildlife-dept',
};

/** A caller who may only look at the map (should the platform ever narrow what a request may do). */
export const viewer: Identity = {
  ...administrator,
  permissions: ['map:read'],
};
