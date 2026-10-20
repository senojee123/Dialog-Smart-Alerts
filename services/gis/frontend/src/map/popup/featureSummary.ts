/**
 * How a feature reads in the popup: its title, and its properties as labelled rows.
 *
 * The API decides which properties a layer exposes; this module only decides what to call them and how
 * to format them. A property the client does not know about is still shown, with its own name split into
 * words - a new layer attribute appears in the popup without a code change.
 */
import { formatArea, formatMetres } from '../editor/geofenceDraft';
import { EVENT_LAYER_ID } from '../layers/layerCatalogue';

export interface SummaryRow {
  readonly key: string;
  readonly label: string;
  readonly value: string;
}

const LABELS: Readonly<Record<string, string>> = {
  name: 'Name',
  nameSi: 'Name (Sinhala)',
  nameTa: 'Name (Tamil)',
  code: 'Code',
  level: 'Level',
  levelName: 'Level name',
  parentId: 'Parent area',
  adminAreaId: 'Administrative area',
  settlementType: 'Settlement type',
  population: 'Population',
  populationYear: 'Population year',
  basis: 'Geometry basis',
  facilityType: 'Facility type',
  class: 'Road class',
  refCode: 'Route number',
  osmHighway: 'OSM highway',
  waterType: 'Water type',
  geometryKind: 'Geometry',
  designation: 'Designation',
  managingAuthority: 'Managing authority',
  iucnCategory: 'IUCN category',
  designatedOn: 'Designated on',
  riskType: 'Risk type',
  severity: 'Severity',
  validFrom: 'Valid from',
  validTo: 'Valid until',
  effectiveFrom: 'In effect from',
  effectiveTo: 'In effect until',
  siteType: 'Site type',
  deviceType: 'Device type',
  siteId: 'Site',
  status: 'Status',
  mountingHeightM: 'Mounting height',
  positionSource: 'Position source',
  positionAccuracyM: 'Position accuracy',
  installedAt: 'Installed',
  decommissionedAt: 'Decommissioned',
  geofenceKind: 'Shape',
  radiusM: 'Radius',
  areaM2: 'Area',
  description: 'Description',
  tenantId: 'Tenant',
  externalId: 'External id',
  sharingPolicy: 'Sharing',
  version: 'Version',
  updatedAt: 'Updated',
  distanceM: 'Distance',
  relation: 'Relation',
  eventId: 'Event',
  eventType: 'Event type',
  eventSubtype: 'Subtype',
  sourceType: 'Source',
  deviceId: 'Device',
  sourceRef: 'Source reference',
  locationSource: 'Location source',
  locationAccuracyM: 'Location accuracy',
  observedAt: 'Observed',
  receivedAt: 'Received',
  refDataRelease: 'Reference data release',
  bearingDeg: 'Bearing',
  fovDeg: 'Field of view',
  rangeM: 'Range',
  geometryMethod: 'Method',
};

/** Properties the client added for its own use, and ones shown in their own place. */
const HIDDEN = new Set(['_featureId', '_layerId', '_deviceState', 'admin', 'name', 'eventId']);

const METRE_KEYS = new Set([
  'distanceM',
  'radiusM',
  'mountingHeightM',
  'positionAccuracyM',
  'locationAccuracyM',
  'rangeM',
]);

export function labelFor(key: string): string {
  const known = LABELS[key];
  if (known !== undefined) {
    return known;
  }
  const words = key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatValue(key: string, value: unknown): string | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no';
  }
  if (typeof value === 'number') {
    if (METRE_KEYS.has(key)) {
      return formatMetres(value);
    }
    if (key === 'areaM2') {
      return formatArea(value);
    }
    if (key === 'bearingDeg' || key === 'fovDeg') {
      return `${value}°`;
    }
    return value.toLocaleString();
  }
  if (typeof value === 'string') {
    return isInstant(key, value) ? formatInstant(value) : value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(', ');
  }
  return JSON.stringify(value);
}

function isInstant(key: string, value: string): boolean {
  return (
    /(At|From|To|On)$/.test(key) && /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?/.test(value)
  );
}

/** Instants are shown in the operator's own time zone, with the zone named so there is no doubt. */
export function formatInstant(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short',
  });
}

export function titleOf(
  layerId: string,
  properties: Readonly<Record<string, unknown>>,
  featureId: string,
): string {
  const name = properties.name;
  if (typeof name === 'string' && name !== '') {
    return name;
  }
  if (layerId === EVENT_LAYER_ID) {
    const type = properties.eventType;
    return typeof type === 'string' ? type : featureId;
  }
  const deviceId = properties.deviceId;
  if (typeof deviceId === 'string' && deviceId !== '') {
    return `Field of view of ${deviceId.slice(0, 8)}`;
  }
  return featureId;
}

/** The feature's properties as rows, in the order the popup should show them. */
export function summaryRows(properties: Readonly<Record<string, unknown>>): readonly SummaryRow[] {
  const rows: SummaryRow[] = [];
  for (const [key, value] of Object.entries(properties)) {
    if (HIDDEN.has(key)) {
      continue;
    }
    const formatted = formatValue(key, value);
    if (formatted !== null) {
      rows.push({ key, label: labelFor(key), value: formatted });
    }
  }
  return rows;
}

export interface AdminCodes {
  readonly l1: string | null;
  readonly l2: string | null;
  readonly l3: string | null;
  readonly l4: string | null;
}

/** The administrative codes an event's geo-context recorded, when it has them. */
export function adminCodesOf(properties: Readonly<Record<string, unknown>>): AdminCodes | null {
  const admin = properties.admin;
  if (typeof admin !== 'object' || admin === null) {
    return null;
  }
  const codes = admin as Record<string, unknown>;
  const read = (key: string): string | null => {
    const value = codes[key];
    return typeof value === 'string' ? value : null;
  };
  const result = { l1: read('l1'), l2: read('l2'), l3: read('l3'), l4: read('l4') };
  return result.l1 === null && result.l2 === null && result.l3 === null && result.l4 === null
    ? null
    : result;
}

export function isEventLayer(layerId: string): boolean {
  return layerId === EVENT_LAYER_ID;
}
