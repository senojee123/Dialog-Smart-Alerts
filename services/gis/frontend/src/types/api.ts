/**
 * API contracts, validated at runtime with zod so that a changed or broken backend response fails
 * loudly at the boundary instead of deep inside the UI.
 *
 * The shapes mirror `backend/app/schemas`; the machine-readable contract is the service's OpenAPI
 * document. Only what the client actually reads is modelled - responses may carry more.
 */
import { z } from 'zod';

export const livenessSchema = z.object({
  status: z.literal('ok'),
  service: z.string(),
  version: z.string(),
});
export type Liveness = z.infer<typeof livenessSchema>;

export const checkStatusSchema = z.enum(['pass', 'warn', 'fail', 'skip']);
export type CheckStatus = z.infer<typeof checkStatusSchema>;

export const readinessCheckSchema = z.object({
  name: z.string(),
  status: checkStatusSchema,
  durationMs: z.number(),
  detail: z.record(z.string(), z.unknown()),
  error: z.string().nullable(),
});
export type ReadinessCheck = z.infer<typeof readinessCheckSchema>;

export const readinessSchema = z.object({
  status: z.enum(['ready', 'not_ready']),
  service: z.string(),
  version: z.string(),
  checks: z.array(readinessCheckSchema),
});
export type Readiness = z.infer<typeof readinessSchema>;

/**
 * GeoJSON position: [longitude, latitude] in WGS84 (RFC 7946).
 *
 * Geometry is read-only throughout: a feature that came from the API is a value, and the geometry
 * helpers in `src/geo` take read-only input, so nothing can quietly rewrite coordinates in place.
 */
export const positionSchema = z
  .tuple([z.number().min(-180).max(180), z.number().min(-90).max(90)])
  .readonly();

export const bboxSchema = z
  .tuple([z.number(), z.number(), z.number(), z.number()])
  .readonly()
  .refine(([minLon, minLat, maxLon, maxLat]) => minLon < maxLon && minLat < maxLat, {
    message: 'bbox must be [minLon, minLat, maxLon, maxLat]',
  });
export type BBox = z.infer<typeof bboxSchema>;

// --- GeoJSON geometry (RFC 7946, no GeometryCollection: the API does not accept or return one) -----

const linearRingSchema = z.array(positionSchema).min(4).readonly();

export const pointSchema = z.object({ type: z.literal('Point'), coordinates: positionSchema });
export const multiPointSchema = z.object({
  type: z.literal('MultiPoint'),
  coordinates: z.array(positionSchema).min(1).readonly(),
});
export const lineStringSchema = z.object({
  type: z.literal('LineString'),
  coordinates: z.array(positionSchema).min(2).readonly(),
});
export const multiLineStringSchema = z.object({
  type: z.literal('MultiLineString'),
  coordinates: z.array(z.array(positionSchema).min(2).readonly()).min(1).readonly(),
});
export const polygonSchema = z.object({
  type: z.literal('Polygon'),
  coordinates: z.array(linearRingSchema).min(1).readonly(),
});
export const multiPolygonSchema = z.object({
  type: z.literal('MultiPolygon'),
  coordinates: z.array(z.array(linearRingSchema).min(1).readonly()).min(1).readonly(),
});

export const geometrySchema = z.discriminatedUnion('type', [
  pointSchema,
  multiPointSchema,
  lineStringSchema,
  multiLineStringSchema,
  polygonSchema,
  multiPolygonSchema,
]);
export type Geometry = z.infer<typeof geometrySchema>;
export type PointGeometry = z.infer<typeof pointSchema>;
export type LineStringGeometry = z.infer<typeof lineStringSchema>;
export type PolygonGeometry = z.infer<typeof polygonSchema>;

export const serviceAreaSchema = z.object({
  type: z.literal('Feature'),
  geometry: polygonSchema,
  properties: z.object({
    bbox: bboxSchema,
    crs: z.literal('EPSG:4326'),
    metricCrs: z.literal('EPSG:5235'),
    description: z.string(),
  }),
});
export type ServiceArea = z.infer<typeof serviceAreaSchema>;

/** RFC 9457 problem details returned for every API error. */
export const problemSchema = z
  .object({
    type: z.string(),
    title: z.string(),
    status: z.number(),
    detail: z.string().optional(),
    instance: z.string().optional(),
    requestId: z.string().optional(),
  })
  .loose();
export type Problem = z.infer<typeof problemSchema>;

// --- Layer catalogue -------------------------------------------------------------------------------

export const capabilitySchema = z.enum(['features', 'within_distance', 'nearest', 'contains']);
export type Capability = z.infer<typeof capabilitySchema>;

export const layerSummarySchema = z.object({
  code: z.string(),
  name: z.string(),
  description: z.string(),
  layerGroup: z.string(),
  geometryTypes: z.array(z.string()),
  srid: z.number(),
  metricSrid: z.number(),
  tenantScoped: z.boolean(),
  defaultSharingPolicy: z.string().nullable(),
  updateFrequency: z.string(),
  nominalAccuracyM: z.number().nullable(),
  queryable: z.boolean(),
  capabilities: z.array(capabilitySchema),
  filters: z.array(z.string()),
  properties: z.array(z.string()),
  timeFiltered: z.boolean(),
  /** Attribution the layer's sources require (reference layers, current release). */
  attribution: z.array(z.string()).default([]),
  /** False when a source's licence does not let the data leave the platform: exports are refused. */
  exportable: z.boolean().default(true),
});
export type LayerSummary = z.infer<typeof layerSummarySchema>;

export const layerCatalogueSchema = z.object({
  layers: z.array(layerSummarySchema),
  refDataRelease: z.string().nullable(),
  /** Every attribution the current reference data release requires; shown on the map. */
  attribution: z.array(z.string()).default([]),
});
export type LayerCatalogue = z.infer<typeof layerCatalogueSchema>;

// --- Features and collections ----------------------------------------------------------------------

/** Feature properties are the layer's exposed attributes; which ones depends on the layer. */
export const featurePropertiesSchema = z.record(z.string(), z.unknown());
export type FeatureProperties = z.infer<typeof featurePropertiesSchema>;

export const featureSchema = z.object({
  type: z.literal('Feature'),
  id: z.string(),
  geometry: geometrySchema.nullable(),
  properties: featurePropertiesSchema,
});
export type ApiFeature = z.infer<typeof featureSchema>;

export const featureCollectionSchema = z.object({
  type: z.literal('FeatureCollection'),
  features: z.array(featureSchema),
  count: z.number(),
  layer: z.string().nullish(),
  nextCursor: z.string().nullish(),
  refDataRelease: z.string().nullish(),
});
export type FeatureCollection = z.infer<typeof featureCollectionSchema>;

export const eventWindowSchema = z.object({ from: z.string(), to: z.string() });
export type EventWindow = z.infer<typeof eventWindowSchema>;

export const eventCollectionSchema = featureCollectionSchema.extend({ window: eventWindowSchema });
export type EventCollection = z.infer<typeof eventCollectionSchema>;

// --- Reverse geocoding -----------------------------------------------------------------------------

export const adminAreaRefSchema = z.object({
  id: z.string(),
  code: z.string(),
  name: z.string(),
  nameSi: z.string().nullable(),
  nameTa: z.string().nullable(),
  level: z.number(),
  levelName: z.string(),
});
export type AdminAreaRef = z.infer<typeof adminAreaRefSchema>;

export const adminCodesSchema = z.object({
  l1: z.string().nullable(),
  l2: z.string().nullable(),
  l3: z.string().nullable(),
  l4: z.string().nullable(),
});
export type AdminCodes = z.infer<typeof adminCodesSchema>;

export const adminHierarchySchema = z.object({
  province: adminAreaRefSchema.nullable(),
  district: adminAreaRefSchema.nullable(),
  dsDivision: adminAreaRefSchema.nullable(),
  gnDivision: adminAreaRefSchema.nullable(),
  codes: adminCodesSchema,
  onBoundary: z.boolean(),
});
export type AdminHierarchy = z.infer<typeof adminHierarchySchema>;

export const nearestSettlementSchema = z.object({
  id: z.string(),
  name: z.string(),
  nameSi: z.string().nullable(),
  nameTa: z.string().nullable(),
  settlementType: z.string(),
  basis: z.enum(['footprint', 'point']),
  distanceM: z.number(),
});
export type NearestSettlement = z.infer<typeof nearestSettlementSchema>;

export const nearestRoadSchema = z.object({
  id: z.string(),
  name: z.string().nullable(),
  class: z.string(),
  refCode: z.string().nullable(),
  distanceM: z.number(),
});
export type NearestRoad = z.infer<typeof nearestRoadSchema>;

export const reverseGeocodeSchema = z.object({
  point: pointSchema,
  admin: adminHierarchySchema,
  nearestSettlement: nearestSettlementSchema.nullable(),
  nearestRoad: nearestRoadSchema.nullable(),
  settlementRadiusM: z.number(),
  roadRadiusM: z.number(),
  missingLayers: z.array(z.string()),
  refDataRelease: z.string(),
  computedAt: z.string(),
});
export type ReverseGeocode = z.infer<typeof reverseGeocodeSchema>;

// --- Operational objects ---------------------------------------------------------------------------

export const sharingPolicySchema = z.enum(['private', 'shared', 'authority_only']);
export type SharingPolicy = z.infer<typeof sharingPolicySchema>;

export const geofenceKindSchema = z.enum(['polygon', 'circle', 'corridor']);
export type GeofenceKind = z.infer<typeof geofenceKindSchema>;

export const geofenceStatusSchema = z.enum(['draft', 'active', 'suspended', 'archived']);
export type GeofenceStatus = z.infer<typeof geofenceStatusSchema>;

export const periodSchema = z.object({ from: z.string().nullable(), to: z.string().nullable() });
export type Period = z.infer<typeof periodSchema>;

export const geofenceDefinitionSchema = z.object({
  kind: geofenceKindSchema,
  geometry: geometrySchema,
  radiusM: z.number().nullable(),
});
export type GeofenceDefinition = z.infer<typeof geofenceDefinitionSchema>;

export const geofenceSchema = z.object({
  id: z.string(),
  tenantId: z.string(),
  name: z.string(),
  description: z.string().nullable(),
  externalId: z.string().nullable(),
  definition: geofenceDefinitionSchema,
  areaM2: z.number(),
  status: geofenceStatusSchema,
  effectiveDuring: periodSchema,
  sharingPolicy: sharingPolicySchema,
  sharedWithTenants: z.array(z.string()),
  attributes: z.record(z.string(), z.unknown()),
  version: z.number(),
  createdAt: z.string(),
  updatedAt: z.string(),
  createdBy: z.string().nullable(),
  updatedBy: z.string().nullable(),
});
export type Geofence = z.infer<typeof geofenceSchema>;

export const geofenceListSchema = z.object({
  items: z.array(geofenceSchema),
  count: z.number(),
  nextCursor: z.string().nullish(),
});
export type GeofenceList = z.infer<typeof geofenceListSchema>;

export const siteStatusSchema = z.enum(['planned', 'active', 'decommissioned']);
export const siteTypeSchema = z.enum([
  'pole',
  'building',
  'junction',
  'checkpoint',
  'estate',
  'perimeter',
  'other',
]);
export const positionSourceSchema = z.enum(['survey', 'gps', 'digitised', 'imagery', 'estimated']);

export const siteSchema = z.object({
  id: z.string(),
  tenantId: z.string(),
  name: z.string(),
  externalId: z.string().nullable(),
  siteType: siteTypeSchema,
  status: siteStatusSchema,
  position: pointSchema,
  positionSource: positionSourceSchema,
  positionAccuracyM: z.number().nullable(),
  sharingPolicy: sharingPolicySchema,
  sharedWithTenants: z.array(z.string()),
  attributes: z.record(z.string(), z.unknown()),
  version: z.number(),
  createdAt: z.string(),
  updatedAt: z.string(),
  createdBy: z.string().nullable(),
  updatedBy: z.string().nullable(),
});
export type Site = z.infer<typeof siteSchema>;

export const siteListSchema = z.object({
  items: z.array(siteSchema),
  count: z.number(),
  nextCursor: z.string().nullish(),
});
export type SiteList = z.infer<typeof siteListSchema>;

export const deviceStatusSchema = z.enum(['planned', 'active', 'inactive', 'decommissioned']);
export type DeviceLifecycleStatus = z.infer<typeof deviceStatusSchema>;

export const deviceTypeSchema = z.enum([
  'camera',
  'anpr_camera',
  'acoustic_sensor',
  'seismic_sensor',
  'environmental_sensor',
  'gateway',
  'other',
]);
export type DeviceType = z.infer<typeof deviceTypeSchema>;

export const fieldOfViewSchema = z.object({
  id: z.string(),
  method: z.enum(['modelled', 'surveyed']),
  bearingDeg: z.number().nullable(),
  fovDeg: z.number().nullable(),
  rangeM: z.number().nullable(),
  geometry: geometrySchema.nullable(),
  validDuring: periodSchema,
});
export type FieldOfView = z.infer<typeof fieldOfViewSchema>;

export const devicePlacementSchema = z.object({
  id: z.string(),
  tenantId: z.string(),
  name: z.string(),
  deviceType: deviceTypeSchema,
  externalId: z.string().nullable(),
  status: deviceStatusSchema,
  siteId: z.string().nullable(),
  position: pointSchema,
  positionSource: positionSourceSchema,
  positionAccuracyM: z.number().nullable(),
  mountingHeightM: z.number().nullable(),
  installedAt: z.string().nullable(),
  decommissionedAt: z.string().nullable(),
  sharingPolicy: sharingPolicySchema,
  sharedWithTenants: z.array(z.string()),
  attributes: z.record(z.string(), z.unknown()),
  fieldOfView: fieldOfViewSchema.nullable(),
  version: z.number(),
  createdAt: z.string(),
  updatedAt: z.string(),
  createdBy: z.string().nullable(),
  updatedBy: z.string().nullable(),
});
export type DevicePlacement = z.infer<typeof devicePlacementSchema>;

// --- The caller and exports ---------------------------------------------------------------------------

/**
 * The permissions `GET /geo/v1/me` reports. A client uses them to decide what to offer. The GIS checks no
 * credentials (the main platform owns sign-in), so every request has the same permissions.
 */
export const PERMISSIONS = [
  'map:read',
  'query:spatial',
  'events:read',
  'geofences:write',
  'assets:write',
  'data:purge',
  'data:export',
  'audit:read',
  'events:enrich',
  'tenants:all',
] as const;
export type Permission = (typeof PERMISSIONS)[number];

export const identitySchema = z.object({
  subject: z.string(),
  clientId: z.string().nullable(),
  // A permission this client does not know yet is kept, not rejected: the answer is still usable.
  permissions: z.array(z.string()),
  tenants: z.array(z.string()),
  allTenants: z.boolean(),
  defaultTenant: z.string().nullable(),
});
export type Identity = z.infer<typeof identitySchema>;

export const featureExportSchema = featureCollectionSchema.extend({
  exportedAt: z.string(),
  tenantId: z.string().nullish(),
  /** What the sources of exported reference data require to be kept with it. */
  attribution: z.array(z.string()).default([]),
});
export type FeatureExport = z.infer<typeof featureExportSchema>;

export const eventExportSchema = featureExportSchema.extend({ window: eventWindowSchema });
export type EventExport = z.infer<typeof eventExportSchema>;
