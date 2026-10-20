/**
 * What the map can show: one entry per layer, with how it is requested and how it is explained.
 *
 * The service publishes its own catalogue (`GET /geo/v1/layers`), which is the authority on what exists
 * and what may be asked of it. This table is the client's side of that: which of those layers this map
 * draws, in what order, from which zoom, in which colour, and what the legend calls them. A layer the
 * service does not publish is dropped when the catalogue arrives, so the map never asks for something
 * the deployment does not have.
 */
import { FILL_OPACITY, PALETTE } from '../palette';
import type { LayerFilters } from '../../services/gisApi';

export type LayerGroupId = 'events' | 'operational' | 'reference';

export interface LegendEntry {
  readonly label: string;
  readonly colour: string;
  readonly shape: 'point' | 'line' | 'area' | 'cluster';
}

export interface LayerRequest {
  readonly filters?: LayerFilters;
  readonly includeGeometry?: boolean;
}

export interface MapLayerDefinition {
  /** Client-side id: the key for visibility, sources and layer ids. */
  readonly id: string;
  /** Layer code in the service's catalogue, or `null` for events (their own endpoint). */
  readonly apiLayer: string | null;
  readonly title: string;
  readonly description: string;
  readonly group: LayerGroupId;
  readonly defaultVisible: boolean;
  /** Below this zoom the layer is not requested: country-wide detail is neither useful nor cheap. */
  readonly minZoom: number;
  readonly legend: readonly LegendEntry[];
  /** What to ask for at this zoom, or `null` to ask for nothing. */
  readonly request?: (zoom: number) => LayerRequest | null;
}

export const LAYER_GROUPS: readonly { readonly id: LayerGroupId; readonly title: string }[] = [
  { id: 'events', title: 'Events' },
  { id: 'operational', title: 'Operational' },
  { id: 'reference', title: 'Reference' },
];

export const EVENT_LAYER_ID = 'events';
export const DEVICE_LAYER_ID = 'devices';
export const FIELD_OF_VIEW_LAYER_ID = 'deviceFieldOfView';
export const GEOFENCE_LAYER_ID = 'geofences';
export const SITE_LAYER_ID = 'sites';

/**
 * Administrative areas by zoom: provinces and districts at country scale, divisions when the operator
 * is looking at a town. Boundary geometry is the heaviest reference data there is, so the level follows
 * the view rather than loading everything.
 */
export function adminLevelForZoom(zoom: number): number {
  if (zoom < 8) {
    return 1;
  }
  if (zoom < 10) {
    return 2;
  }
  if (zoom < 12) {
    return 3;
  }
  return 4;
}

/** Ordered bottom to top: areas first, then lines, then points, then events on top. */
export const MAP_LAYERS: readonly MapLayerDefinition[] = [
  {
    id: 'adminAreas',
    apiLayer: 'ref.admin_area',
    title: 'Administrative areas',
    description: 'Provinces, districts, DS and GN divisions; the level follows the zoom.',
    group: 'reference',
    defaultVisible: true,
    minZoom: 0,
    legend: [{ label: 'Boundary', colour: PALETTE.adminBoundary, shape: 'line' }],
    request: (zoom) => ({ filters: { level: adminLevelForZoom(zoom) } }),
  },
  {
    id: 'protectedAreas',
    apiLayer: 'ref.protected_area',
    title: 'Protected areas',
    description: 'National parks, reserves and sanctuaries, with their managing authority.',
    group: 'reference',
    defaultVisible: true,
    minZoom: 6,
    legend: [{ label: 'Protected area', colour: PALETTE.protectedArea, shape: 'area' }],
  },
  {
    id: 'riskZones',
    apiLayer: 'ref.risk_zone',
    title: 'Risk zones',
    description: 'Zones in effect now, shaded by severity.',
    group: 'reference',
    defaultVisible: false,
    minZoom: 6,
    legend: [
      { label: 'Severity 1-2', colour: '#fdba74', shape: 'area' },
      { label: 'Severity 3', colour: '#fb923c', shape: 'area' },
      { label: 'Severity 4-5', colour: PALETTE.riskZone, shape: 'area' },
    ],
  },
  {
    id: 'waterBodies',
    apiLayer: 'ref.water_body',
    title: 'Water',
    description: 'Tanks, lakes, rivers and canals.',
    group: 'reference',
    defaultVisible: true,
    minZoom: 8,
    legend: [{ label: 'Water body', colour: PALETTE.water, shape: 'area' }],
  },
  {
    id: 'roads',
    apiLayer: 'ref.road',
    title: 'Roads',
    description: 'Road network by class; the trunk classes appear first.',
    group: 'reference',
    defaultVisible: true,
    minZoom: 9,
    legend: [
      { label: 'A road', colour: '#3f3f46', shape: 'line' },
      { label: 'B road', colour: PALETTE.road, shape: 'line' },
      { label: 'Other', colour: '#a1a1aa', shape: 'line' },
    ],
  },
  {
    id: 'settlements',
    apiLayer: 'ref.settlement',
    title: 'Settlements',
    description: 'Cities, towns and villages, as footprints where the release has them.',
    group: 'reference',
    defaultVisible: true,
    minZoom: 7,
    legend: [{ label: 'Settlement', colour: PALETTE.settlement, shape: 'point' }],
  },
  {
    id: 'facilities',
    apiLayer: 'ref.facility',
    title: 'Facilities',
    description: 'Hospitals, schools, police and other points of interest.',
    group: 'reference',
    defaultVisible: false,
    minZoom: 10,
    legend: [{ label: 'Facility', colour: PALETTE.facility, shape: 'point' }],
  },
  {
    id: GEOFENCE_LAYER_ID,
    apiLayer: 'ops.geofence',
    title: 'Geofences',
    description: "The tenant's geofences and those shared with it.",
    group: 'operational',
    defaultVisible: true,
    minZoom: 0,
    legend: [
      { label: 'Active', colour: PALETTE.geofence, shape: 'area' },
      { label: 'Draft', colour: PALETTE.geofenceDraft, shape: 'area' },
      { label: 'Suspended', colour: PALETTE.geofenceSuspended, shape: 'area' },
    ],
  },
  {
    id: FIELD_OF_VIEW_LAYER_ID,
    apiLayer: 'ops.device_field_of_view',
    title: 'Fields of view',
    description: 'What each camera or sensor observes, where it is recorded.',
    group: 'operational',
    defaultVisible: true,
    minZoom: 10,
    legend: [{ label: 'Field of view', colour: PALETTE.fieldOfView, shape: 'area' }],
  },
  {
    id: SITE_LAYER_ID,
    apiLayer: 'ops.site',
    title: 'Sites',
    description: 'Installation sites: poles, buildings, junctions and checkpoints.',
    group: 'operational',
    defaultVisible: false,
    minZoom: 9,
    legend: [{ label: 'Site', colour: PALETTE.site, shape: 'point' }],
  },
  {
    id: DEVICE_LAYER_ID,
    apiLayer: 'ops.device',
    title: 'Devices',
    description: 'Where each device is, with the state an external service reports for it.',
    group: 'operational',
    defaultVisible: true,
    minZoom: 8,
    legend: [
      { label: 'Online', colour: PALETTE.deviceActive, shape: 'point' },
      { label: 'Degraded', colour: PALETTE.deviceInactive, shape: 'point' },
      { label: 'Offline', colour: PALETTE.deviceOffline, shape: 'point' },
      { label: 'Not reported', colour: PALETTE.deviceUnknown, shape: 'point' },
    ],
  },
  {
    id: EVENT_LAYER_ID,
    apiLayer: null,
    title: 'Events',
    description: 'Event locations in the chosen window, clustered until they separate.',
    group: 'events',
    defaultVisible: true,
    minZoom: 0,
    legend: [
      { label: 'Event', colour: PALETTE.event, shape: 'point' },
      { label: 'Cluster', colour: PALETTE.eventCluster, shape: 'cluster' },
    ],
  },
];

export const MAP_LAYERS_BY_ID: ReadonlyMap<string, MapLayerDefinition> = new Map(
  MAP_LAYERS.map((layer) => [layer.id, layer]),
);

/** Feature layers (everything but events, which have their own endpoint and their own component). */
export const FEATURE_LAYERS: readonly MapLayerDefinition[] = MAP_LAYERS.filter(
  (layer) => layer.apiLayer !== null,
);

export function layerById(id: string): MapLayerDefinition | undefined {
  return MAP_LAYERS_BY_ID.get(id);
}

/** Opacity for an area layer, so overlapping areas stay legible. */
export const AREA_OPACITY = FILL_OPACITY;
