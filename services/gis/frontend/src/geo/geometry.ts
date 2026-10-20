/**
 * GeoJSON geometry helpers: bounds, containment, validity, area and circle construction.
 *
 * Metric work goes through `sld99.ts`, so an area or a radius here is the same quantity the API
 * reports. Nothing in this module talks to the API or to MapLibre; it is pure geometry.
 */
import type { BBox, Geometry, PolygonGeometry } from '../types/api';
import { distanceM, toMetric, toWgs84, type MetricPoint, type Position } from './sld99';

/** `[minLon, minLat, maxLon, maxLat]` in WGS84 degrees, as the API's `bbox` parameter orders them. */
export type Bounds = readonly [number, number, number, number];

export type Ring = readonly Position[];
export type PolygonRings = readonly Ring[];

const CIRCLE_SEGMENTS = 128;
const WEB_MERCATOR_RADIUS = 6378137;

/** Every position in a geometry, in document order. */
export function positionsOf(geometry: Geometry): readonly Position[] {
  switch (geometry.type) {
    case 'Point':
      return [geometry.coordinates];
    case 'MultiPoint':
    case 'LineString':
      return geometry.coordinates;
    case 'MultiLineString':
    case 'Polygon':
      return geometry.coordinates.flat();
    case 'MultiPolygon':
      return geometry.coordinates.flat(2);
  }
}

export function boundsOfPositions(positions: readonly Position[]): Bounds | null {
  if (positions.length === 0) {
    return null;
  }
  let minLon = Number.POSITIVE_INFINITY;
  let minLat = Number.POSITIVE_INFINITY;
  let maxLon = Number.NEGATIVE_INFINITY;
  let maxLat = Number.NEGATIVE_INFINITY;
  for (const [lon, lat] of positions) {
    minLon = Math.min(minLon, lon);
    minLat = Math.min(minLat, lat);
    maxLon = Math.max(maxLon, lon);
    maxLat = Math.max(maxLat, lat);
  }
  return [minLon, minLat, maxLon, maxLat];
}

export function boundsOf(geometry: Geometry): Bounds | null {
  return boundsOfPositions(positionsOf(geometry));
}

export function boundsOfGeometries(geometries: readonly Geometry[]): Bounds | null {
  return boundsOfPositions(geometries.flatMap((geometry) => [...positionsOf(geometry)]));
}

/** Grow bounds by a fraction of their own size, with a floor so a single point still has extent. */
export function padBounds(bounds: Bounds, fraction: number, minimumDegrees = 0.0005): Bounds {
  const [minLon, minLat, maxLon, maxLat] = bounds;
  const lonPad = Math.max((maxLon - minLon) * fraction, minimumDegrees);
  const latPad = Math.max((maxLat - minLat) * fraction, minimumDegrees);
  return [minLon - lonPad, minLat - latPad, maxLon + lonPad, maxLat + latPad];
}

export function boundsContain(outer: Bounds, inner: Bounds): boolean {
  return (
    outer[0] <= inner[0] && outer[1] <= inner[1] && outer[2] >= inner[2] && outer[3] >= inner[3]
  );
}

export function boundsIntersect(a: Bounds, b: Bounds): boolean {
  return a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];
}

/** The overlap of two bounds, or `null` when they do not overlap. */
export function intersectBounds(a: Bounds, b: Bounds): Bounds | null {
  if (!boundsIntersect(a, b)) {
    return null;
  }
  return [
    Math.max(a[0], b[0]),
    Math.max(a[1], b[1]),
    Math.min(a[2], b[2]),
    Math.min(a[3], b[3]),
  ];
}

export function boundsContainPosition(bounds: Bounds, [lon, lat]: Position): boolean {
  return bounds[0] <= lon && lon <= bounds[2] && bounds[1] <= lat && lat <= bounds[3];
}

/** The API's `bbox` query parameter: four ordered numbers, six decimals (~10 cm). */
export function boundsToParameter(bounds: Bounds): string {
  return bounds.map((value) => Number(value.toFixed(6))).join(',');
}

export function boundsFromBbox(bbox: BBox): Bounds {
  return [bbox[0], bbox[1], bbox[2], bbox[3]];
}

// --- containment -----------------------------------------------------------------------------------

function onSegment(position: Position, from: Position, to: Position): boolean {
  const [x, y] = position;
  const [x1, y1] = from;
  const [x2, y2] = to;
  const cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1);
  if (Math.abs(cross) > 1e-12) {
    return false;
  }
  return (
    Math.min(x1, x2) - 1e-12 <= x &&
    x <= Math.max(x1, x2) + 1e-12 &&
    Math.min(y1, y2) - 1e-12 <= y &&
    y <= Math.max(y1, y2) + 1e-12
  );
}

/**
 * Ray casting, with the boundary counted as inside - the same rule the API applies (`ST_Covers`), so a
 * position on the edge of a drawn shape is treated the same way on both sides.
 */
export function pointInRing(position: Position, ring: Ring): boolean {
  const [x, y] = position;
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
    const current = ring[index];
    const before = ring[previous];
    if (current === undefined || before === undefined) {
      continue;
    }
    if (onSegment(position, before, current)) {
      return true;
    }
    const [xi, yi] = current;
    const [xj, yj] = before;
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/** A polygon contains a position when its first ring does and no hole excludes it. */
export function pointInPolygon(position: Position, rings: PolygonRings): boolean {
  const [exterior, ...holes] = rings;
  if (exterior === undefined || !pointInRing(position, exterior)) {
    return false;
  }
  return !holes.some((hole) => pointInRing(position, hole) && !isOnRing(position, hole));
}

function isOnRing(position: Position, ring: Ring): boolean {
  for (let index = 1; index < ring.length; index += 1) {
    const from = ring[index - 1];
    const to = ring[index];
    if (from !== undefined && to !== undefined && onSegment(position, from, to)) {
      return true;
    }
  }
  return false;
}

/**
 * Whether an areal geometry contains a position. Points and lines contain nothing: this is the
 * client-side filter for "inside the shape I drew", not a general spatial predicate - the API answers
 * those (`POST /geo/v1/query/contains`).
 */
export function pointInGeometry(position: Position, geometry: Geometry): boolean {
  if (geometry.type === 'Polygon') {
    return pointInPolygon(position, geometry.coordinates);
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some((rings) => pointInPolygon(position, rings));
  }
  return false;
}

/** Whether any position of `geometry` lies inside `area`. Cheap stand-in for a real intersection. */
export function geometryTouchesArea(geometry: Geometry, area: Geometry): boolean {
  return positionsOf(geometry).some((position) => pointInGeometry(position, area));
}

// --- validity --------------------------------------------------------------------------------------

export function ringIsClosed(ring: Ring): boolean {
  const first = ring[0];
  const last = ring[ring.length - 1];
  return first?.[0] === last?.[0] && first?.[1] === last?.[1] && first !== undefined;
}

export function closeRing(ring: Ring): Ring {
  const first = ring[0];
  return first !== undefined && !ringIsClosed(ring) ? [...ring, first] : ring;
}

function segmentsCross(a1: Position, a2: Position, b1: Position, b2: Position): boolean {
  const orientation = (p: Position, q: Position, r: Position): number => {
    const value = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
    if (Math.abs(value) < 1e-14) {
      return 0;
    }
    return value > 0 ? 1 : -1;
  };
  const o1 = orientation(a1, a2, b1);
  const o2 = orientation(a1, a2, b2);
  const o3 = orientation(b1, b2, a1);
  const o4 = orientation(b1, b2, a2);
  if (o1 !== o2 && o3 !== o4) {
    return true;
  }
  // Collinear overlap counts as crossing; touching at a shared endpoint is handled by the caller.
  return (
    (o1 === 0 && onSegment(b1, a1, a2)) ||
    (o2 === 0 && onSegment(b2, a1, a2)) ||
    (o3 === 0 && onSegment(a1, b1, b2)) ||
    (o4 === 0 && onSegment(a2, b1, b2))
  );
}

/**
 * Whether a ring crosses itself. Drawn rings have tens of vertices, so the pairwise test is cheaper
 * than a sweep and has no edge cases; segments that merely share an endpoint do not count.
 */
export function ringSelfIntersects(ring: Ring): boolean {
  const closed = closeRing(ring);
  const count = closed.length - 1;
  for (let i = 0; i < count; i += 1) {
    for (let j = i + 1; j < count; j += 1) {
      const adjacent = j === i + 1 || (i === 0 && j === count - 1);
      const a1 = closed[i];
      const a2 = closed[i + 1];
      const b1 = closed[j];
      const b2 = closed[j + 1];
      if (a1 === undefined || a2 === undefined || b1 === undefined || b2 === undefined) {
        continue;
      }
      if (adjacent) {
        continue;
      }
      if (segmentsCross(a1, a2, b1, b2)) {
        return true;
      }
    }
  }
  return false;
}

/** Signed area of a ring in square metres on the EPSG:5235 plane; positive when counter-clockwise. */
export function signedRingAreaM2(ring: Ring): number {
  const closed = closeRing(ring).map(toMetric);
  let sum = 0;
  for (let index = 1; index < closed.length; index += 1) {
    const previous = closed[index - 1];
    const current = closed[index];
    if (previous !== undefined && current !== undefined) {
      sum += previous[0] * current[1] - current[0] * previous[1];
    }
  }
  return sum / 2;
}

/** Area of an areal geometry in square metres, holes subtracted. Non-areal geometries measure zero. */
export function areaM2(geometry: Geometry): number {
  const polygons =
    geometry.type === 'Polygon'
      ? [geometry.coordinates]
      : geometry.type === 'MultiPolygon'
        ? geometry.coordinates
        : [];
  return polygons.reduce((total, rings) => {
    const [exterior, ...holes] = rings;
    if (exterior === undefined) {
      return total;
    }
    const outer = Math.abs(signedRingAreaM2(exterior));
    const inner = holes.reduce((sum, hole) => sum + Math.abs(signedRingAreaM2(hole)), 0);
    return total + outer - inner;
  }, 0);
}

// --- construction ----------------------------------------------------------------------------------

/**
 * The circle of `radiusM` around `centre`, as a polygon on the EPSG:5235 plane.
 *
 * This is how a circle geofence is *drawn*; what is stored and tested is the centre and the radius, so
 * the number of segments affects only what the operator sees.
 */
export function circlePolygon(
  centre: Position,
  radiusM: number,
  segments = CIRCLE_SEGMENTS,
): PolygonGeometry {
  const [easting, northing] = toMetric(centre);
  const steps = Math.max(8, Math.trunc(segments));
  const ring: Position[] = [];
  for (let index = 0; index < steps; index += 1) {
    const angle = (2 * Math.PI * index) / steps;
    const point: MetricPoint = [
      easting + radiusM * Math.sin(angle),
      northing + radiusM * Math.cos(angle),
    ];
    ring.push(toWgs84(point));
  }
  const first = ring[0];
  if (first !== undefined) {
    ring.push(first);
  }
  return { type: 'Polygon', coordinates: [ring] };
}

// --- Web Mercator ----------------------------------------------------------------------------------
// Terra Draw draws a circle as a ring of positions at equal angles around its centre *in Web Mercator*,
// the projection the map is rendered in. Averaging the ring there recovers the centre exactly; in any
// other space the projection's distortion would displace it.

export function toWebMercator([lon, lat]: Position): MetricPoint {
  const clamped = Math.max(-85.051129, Math.min(85.051129, lat));
  return [
    (lon * Math.PI * WEB_MERCATOR_RADIUS) / 180,
    WEB_MERCATOR_RADIUS * Math.log(Math.tan(Math.PI / 4 + (clamped * Math.PI) / 360)),
  ];
}

export function fromWebMercator([x, y]: MetricPoint): Position {
  return [
    (x * 180) / (Math.PI * WEB_MERCATOR_RADIUS),
    (360 / Math.PI) * (Math.atan(Math.exp(y / WEB_MERCATOR_RADIUS)) - Math.PI / 4),
  ];
}

/** The Web Mercator centre of a ring of positions, e.g. a circle Terra Draw drew. */
export function webMercatorCentre(positions: readonly Position[]): Position | null {
  const ring = ringIsClosed(positions) ? positions.slice(0, -1) : positions;
  if (ring.length === 0) {
    return null;
  }
  let x = 0;
  let y = 0;
  for (const position of ring) {
    const [px, py] = toWebMercator(position);
    x += px;
    y += py;
  }
  return fromWebMercator([x / ring.length, y / ring.length]);
}

/** Mean distance in metres from `centre` to each position: the radius of a drawn circle. */
export function meanRadiusM(centre: Position, positions: readonly Position[]): number {
  const ring = ringIsClosed(positions) ? positions.slice(0, -1) : positions;
  if (ring.length === 0) {
    return 0;
  }
  return ring.reduce((total, position) => total + distanceM(centre, position), 0) / ring.length;
}
