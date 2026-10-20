/**
 * The geofence being edited, and what makes it valid.
 *
 * The draft is the definition - a polygon, or a centre and a radius, or a centre line and a half-width
 * - because that is what the service stores and what it tests hits against. Terra Draw is the input
 * device: what it produces is converted here, and the draft is what the map draws and what is sent.
 *
 * The checks mirror the ones the service applies (`backend/app/schemas/operational.py`), so an operator
 * is told about a problem while drawing rather than after a round trip. They do not replace them: the
 * service validates every request, and its problem details are shown when they differ.
 */
import {
  areaM2,
  boundsContainPosition,
  closeRing,
  positionsOf,
  ringIsClosed,
  ringSelfIntersects,
  type Bounds,
} from '../../geo/geometry';
import { distanceM, pathLengthM, type Position } from '../../geo/sld99';
import type { GeofenceInput } from '../../services/gisApi';
import type { Geofence, GeofenceStatus, Geometry, SharingPolicy } from '../../types/api';
import type { DraftShape } from '../layers/draftShape';

export type DraftKind = 'polygon' | 'circle' | 'corridor';

export const MAX_CIRCLE_RADIUS_M = 50_000;
export const MAX_CORRIDOR_HALF_WIDTH_M = 5_000;
export const MAX_NAME_LENGTH = 200;
export const MAX_DESCRIPTION_LENGTH = 1_000;
const TENANT_ID = /^[a-z0-9][a-z0-9_-]{1,62}$/;

export interface GeofenceDraft {
  /** Set when an existing geofence is being changed; `null` while creating one. */
  readonly id: string | null;
  readonly version: number | null;
  readonly name: string;
  readonly description: string;
  readonly externalId: string;
  readonly kind: DraftKind;
  /** The definition geometry: a polygon, a centre point or a centre line. */
  readonly geometry: Geometry | null;
  readonly radiusM: number | null;
  readonly status: GeofenceStatus;
  readonly sharingPolicy: SharingPolicy;
  readonly sharedWithTenants: readonly string[];
  readonly effectiveFrom: string | null;
  readonly effectiveTo: string | null;
  /**
   * Properties of the author's own. The GIS service stores them and does not interpret them; a replace
   * is a full replace, so they travel with the draft or they would be lost.
   */
  readonly attributes: Readonly<Record<string, unknown>>;
}

export interface DraftIssue {
  readonly field: string;
  readonly message: string;
}

const DEFAULT_RADIUS_M: Readonly<Record<DraftKind, number | null>> = {
  polygon: null,
  circle: 500,
  corridor: 50,
};

export function emptyDraft(kind: DraftKind): GeofenceDraft {
  return {
    id: null,
    version: null,
    name: '',
    description: '',
    externalId: '',
    kind,
    geometry: null,
    radiusM: DEFAULT_RADIUS_M[kind],
    status: 'active',
    sharingPolicy: 'private',
    sharedWithTenants: [],
    effectiveFrom: null,
    effectiveTo: null,
    attributes: {},
  };
}

/** Load an existing geofence into the editor, definition and all. */
export function draftFromGeofence(geofence: Geofence): GeofenceDraft {
  return {
    id: geofence.id,
    version: geofence.version,
    name: geofence.name,
    description: geofence.description ?? '',
    externalId: geofence.externalId ?? '',
    kind: geofence.definition.kind,
    geometry: geofence.definition.geometry,
    radiusM: geofence.definition.radiusM,
    status: geofence.status,
    sharingPolicy: geofence.sharingPolicy,
    sharedWithTenants: geofence.sharedWithTenants,
    effectiveFrom: geofence.effectiveDuring.from,
    effectiveTo: geofence.effectiveDuring.to,
    attributes: geofence.attributes,
  };
}

export interface DrawnFeature {
  readonly geometry: Geometry;
  readonly properties?: Readonly<Record<string, unknown>>;
}

/**
 * What a drawn feature means as a definition.
 *
 * Terra Draw draws a circle as a ring of positions; the definition is its centre and its radius, so the
 * ring is measured rather than stored. A polygon and a corridor's centre line are used as drawn.
 */
export function definitionFromDrawn(
  kind: DraftKind,
  feature: DrawnFeature,
  centreOf: (positions: readonly Position[]) => Position | null,
  radiusOf: (centre: Position, positions: readonly Position[]) => number,
): { readonly geometry: Geometry; readonly radiusM: number | null } | null {
  if (kind === 'circle') {
    if (feature.geometry.type !== 'Polygon') {
      return null;
    }
    const ring = feature.geometry.coordinates[0];
    if (ring === undefined) {
      return null;
    }
    const centre = centreOf(ring);
    if (centre === null) {
      return null;
    }
    return {
      geometry: { type: 'Point', coordinates: centre },
      radiusM: Math.round(radiusOf(centre, ring) * 100) / 100,
    };
  }
  if (kind === 'corridor') {
    return feature.geometry.type === 'LineString' || feature.geometry.type === 'MultiLineString'
      ? { geometry: feature.geometry, radiusM: null }
      : null;
  }
  return feature.geometry.type === 'Polygon' || feature.geometry.type === 'MultiPolygon'
    ? { geometry: feature.geometry, radiusM: null }
    : null;
}

function ringIssues(ring: readonly Position[], label: string): DraftIssue[] {
  const issues: DraftIssue[] = [];
  const closed = closeRing(ring);
  if (closed.length < 4) {
    issues.push({ field: 'geometry', message: `${label} needs at least three distinct corners.` });
  }
  if (!ringIsClosed(ring) && ring.length < 3) {
    issues.push({ field: 'geometry', message: `${label} is not a closed shape.` });
  }
  if (closed.length >= 4 && ringSelfIntersects(closed)) {
    issues.push({ field: 'geometry', message: `${label} crosses itself.` });
  }
  return issues;
}

function polygonIssues(geometry: Geometry): DraftIssue[] {
  if (geometry.type === 'Polygon') {
    return geometry.coordinates.flatMap((ring, index) =>
      ringIssues(ring, index === 0 ? 'The area' : 'A hole in the area'),
    );
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.flatMap((rings) =>
      rings.flatMap((ring, index) => ringIssues(ring, index === 0 ? 'An area' : 'A hole in an area')),
    );
  }
  return [{ field: 'geometry', message: 'A polygon geofence needs an area.' }];
}

/** Everything wrong with the draft, in the order an operator would fix it. */
export function validateDraft(draft: GeofenceDraft, serviceArea: Bounds | null): readonly DraftIssue[] {
  const issues: DraftIssue[] = [];
  const name = draft.name.trim();
  if (name === '') {
    issues.push({ field: 'name', message: 'A geofence needs a name.' });
  } else if (name.length > MAX_NAME_LENGTH) {
    issues.push({ field: 'name', message: `The name must be ${MAX_NAME_LENGTH} characters or fewer.` });
  }
  if (draft.description.length > MAX_DESCRIPTION_LENGTH) {
    issues.push({
      field: 'description',
      message: `The description must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`,
    });
  }

  if (draft.geometry === null) {
    issues.push({ field: 'geometry', message: 'Draw the geofence on the map.' });
  } else {
    issues.push(...geometryIssues(draft));
    if (serviceArea !== null) {
      const outside = positionsOf(draft.geometry).some(
        (position) => !boundsContainPosition(serviceArea, position),
      );
      if (outside) {
        issues.push({ field: 'geometry', message: 'The geofence reaches outside the service area.' });
      }
    }
  }

  if (draft.sharedWithTenants.length > 0 && draft.sharingPolicy !== 'shared') {
    issues.push({
      field: 'sharedWithTenants',
      message: "Naming tenants requires the sharing policy 'shared'.",
    });
  }
  for (const tenant of draft.sharedWithTenants) {
    if (!TENANT_ID.test(tenant)) {
      issues.push({ field: 'sharedWithTenants', message: `'${tenant}' is not a tenant id.` });
    }
  }
  if (new Set(draft.sharedWithTenants).size !== draft.sharedWithTenants.length) {
    issues.push({ field: 'sharedWithTenants', message: 'A tenant is named twice.' });
  }

  if (draft.effectiveFrom !== null && draft.effectiveTo !== null) {
    if (new Date(draft.effectiveTo).getTime() <= new Date(draft.effectiveFrom).getTime()) {
      issues.push({ field: 'effectiveDuring', message: "'To' must be after 'from'." });
    }
  }
  return issues;
}

function geometryIssues(draft: GeofenceDraft): readonly DraftIssue[] {
  const geometry = draft.geometry;
  if (geometry === null) {
    return [];
  }
  switch (draft.kind) {
    case 'polygon':
      return [
        ...polygonIssues(geometry),
        ...(draft.radiusM === null
          ? []
          : [{ field: 'radiusM', message: 'A polygon geofence has no radius.' }]),
      ];
    case 'circle':
      return [
        ...(geometry.type === 'Point'
          ? []
          : [{ field: 'geometry', message: 'A circle geofence needs a centre point.' }]),
        ...radiusIssues(draft.radiusM, MAX_CIRCLE_RADIUS_M, 'radius'),
      ];
    case 'corridor':
      return [
        ...(geometry.type === 'LineString' || geometry.type === 'MultiLineString'
          ? positionsOf(geometry).length >= 2
            ? []
            : [{ field: 'geometry', message: 'A corridor needs at least two positions.' }]
          : [{ field: 'geometry', message: 'A corridor geofence needs a centre line.' }]),
        ...radiusIssues(draft.radiusM, MAX_CORRIDOR_HALF_WIDTH_M, 'half-width'),
      ];
  }
}

function radiusIssues(radiusM: number | null, maximum: number, label: string): DraftIssue[] {
  if (radiusM === null || Number.isNaN(radiusM)) {
    return [{ field: 'radiusM', message: `Set the ${label} in metres.` }];
  }
  if (radiusM <= 0) {
    return [{ field: 'radiusM', message: `The ${label} must be more than zero.` }];
  }
  if (radiusM > maximum) {
    return [
      { field: 'radiusM', message: `The ${label} must be ${maximum.toLocaleString()} m or less.` },
    ];
  }
  return [];
}

export function draftIsValid(draft: GeofenceDraft, serviceArea: Bounds | null): boolean {
  return validateDraft(draft, serviceArea).length === 0;
}

/** The request body for `POST`/`PUT /geo/v1/geofences`. */
export function draftToInput(draft: GeofenceDraft): GeofenceInput {
  if (draft.geometry === null) {
    throw new Error('a geofence draft without a geometry cannot be sent');
  }
  return {
    name: draft.name.trim(),
    description: draft.description.trim() === '' ? null : draft.description.trim(),
    externalId: draft.externalId.trim() === '' ? null : draft.externalId.trim(),
    definition: {
      kind: draft.kind,
      geometry: draft.geometry,
      ...(draft.kind === 'polygon' || draft.radiusM === null ? {} : { radiusM: draft.radiusM }),
    },
    status: draft.status,
    effectiveDuring: { from: draft.effectiveFrom, to: draft.effectiveTo },
    sharingPolicy: draft.sharingPolicy,
    sharedWithTenants: draft.sharedWithTenants,
    attributes: draft.attributes,
    ...(draft.version === null ? {} : { version: draft.version }),
  };
}

/** What the map draws for the draft. */
export function draftShape(draft: GeofenceDraft): DraftShape | null {
  return draft.geometry === null
    ? null
    : { kind: draft.kind, geometry: draft.geometry, radiusM: draft.radiusM };
}

/**
 * The area of the draft in square metres, as the service would compute it: exact for a circle, the
 * polygon's own area for a polygon, and the corridor's length times its width plus its round ends.
 */
export function draftAreaM2(draft: GeofenceDraft): number | null {
  const geometry = draft.geometry;
  if (geometry === null) {
    return null;
  }
  if (draft.kind === 'circle') {
    return draft.radiusM === null ? null : Math.PI * draft.radiusM ** 2;
  }
  if (draft.kind === 'corridor') {
    if (draft.radiusM === null) {
      return null;
    }
    const length = lengthOf(geometry);
    return length * 2 * draft.radiusM + Math.PI * draft.radiusM ** 2;
  }
  return areaM2(geometry);
}

function lengthOf(geometry: Geometry): number {
  if (geometry.type === 'LineString') {
    return pathLengthM(geometry.coordinates);
  }
  if (geometry.type === 'MultiLineString') {
    return geometry.coordinates.reduce((total, line) => total + pathLengthM(line), 0);
  }
  return 0;
}

/** A short description of the drawn shape, for the editor's summary line. */
export function describeDraft(draft: GeofenceDraft): string {
  const geometry = draft.geometry;
  if (geometry === null) {
    return 'Nothing drawn yet';
  }
  if (draft.kind === 'circle' && geometry.type === 'Point') {
    const [lon, lat] = geometry.coordinates;
    const radius = draft.radiusM === null ? '?' : `${Math.round(draft.radiusM)} m`;
    return `Circle of ${radius} at ${lat.toFixed(4)}, ${lon.toFixed(4)}`;
  }
  if (draft.kind === 'corridor') {
    const half = draft.radiusM === null ? '?' : `${Math.round(draft.radiusM)} m`;
    return `Corridor ${formatMetres(lengthOf(geometry))} long, ${half} each side`;
  }
  return `Area of ${formatArea(areaM2(geometry))}, ${positionsOf(geometry).length} positions`;
}

export function formatMetres(metres: number): string {
  return metres >= 1000 ? `${(metres / 1000).toFixed(2)} km` : `${metres.toFixed(metres < 10 ? 1 : 0)} m`;
}

export function formatArea(squareMetres: number): string {
  return squareMetres >= 1_000_000
    ? `${(squareMetres / 1_000_000).toFixed(2)} km²`
    : `${Math.round(squareMetres).toLocaleString()} m²`;
}

/** The tenants named in the editor's field, as the request will carry them. */
export function parseTenants(value: string): readonly string[] {
  return value
    .split(',')
    .map((tenant) => tenant.trim())
    .filter((tenant) => tenant !== '');
}

/** Distance between the first and last position of a drawn line, for the editor's summary. */
export function spanOf(positions: readonly Position[]): number {
  const first = positions[0];
  const last = positions[positions.length - 1];
  return first === undefined || last === undefined ? 0 : distanceM(first, last);
}
