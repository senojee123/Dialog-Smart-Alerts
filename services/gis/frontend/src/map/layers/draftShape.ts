/**
 * The shape of a geofence being drawn, and how it is drawn.
 *
 * A circle's definition is a centre and a radius; what is *drawn* is the polygon of that circle on the
 * EPSG:5235 plane, so the operator sees the shape the service will store rather than an approximation.
 */
import { circlePolygon } from '../../geo/geometry';
import type { Geometry } from '../../types/api';

export interface DraftShape {
  readonly kind: 'polygon' | 'circle' | 'corridor';
  readonly geometry: Geometry;
  readonly radiusM: number | null;
}

/** What to draw for a draft: a circle becomes its exact polygon, anything else is drawn as given. */
export function draftGeometry(draft: DraftShape): Geometry {
  if (draft.kind === 'circle' && draft.radiusM !== null && draft.geometry.type === 'Point') {
    return circlePolygon(draft.geometry.coordinates, draft.radiusM);
  }
  return draft.geometry;
}

/** Centre of Sri Lanka: the fallback anchor for a width given in metres. */
const DEFAULT_LATITUDE = 7.85;

/** Latitude the metres-to-pixels conversion is anchored at: the middle of the drawn shape. */
export function draftAnchorLatitude(draft: DraftShape | null): number {
  if (draft === null) {
    return DEFAULT_LATITUDE;
  }
  const geometry = draft.geometry;
  if (geometry.type === 'Point') {
    return geometry.coordinates[1];
  }
  if (geometry.type === 'LineString') {
    const latitudes = geometry.coordinates.map((position) => position[1]);
    return (Math.min(...latitudes) + Math.max(...latitudes)) / 2;
  }
  return DEFAULT_LATITUDE;
}
