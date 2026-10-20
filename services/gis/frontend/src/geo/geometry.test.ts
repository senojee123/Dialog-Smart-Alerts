import { describe, expect, it } from 'vitest';

import {
  areaM2,
  boundsContain,
  boundsContainPosition,
  boundsIntersect,
  boundsOf,
  boundsOfGeometries,
  boundsOfPositions,
  boundsToParameter,
  circlePolygon,
  closeRing,
  fromWebMercator,
  geometryTouchesArea,
  intersectBounds,
  meanRadiusM,
  padBounds,
  pointInGeometry,
  pointInPolygon,
  pointInRing,
  positionsOf,
  ringIsClosed,
  ringSelfIntersects,
  signedRingAreaM2,
  toWebMercator,
  webMercatorCentre,
  type Bounds,
  type Ring,
} from './geometry';
import { distanceM, type Position } from './sld99';
import type { Geometry } from '../types/api';

const SQUARE: Ring = [
  [80.7, 8.0],
  [80.8, 8.0],
  [80.8, 8.1],
  [80.7, 8.1],
  [80.7, 8.0],
];

const HABARANA: Position = [80.7513, 8.0342];

describe('positionsOf', () => {
  it('flattens every geometry type the API returns', () => {
    expect(positionsOf({ type: 'Point', coordinates: HABARANA })).toHaveLength(1);
    expect(
      positionsOf({ type: 'LineString', coordinates: [HABARANA, [80.76, 8.04]] }),
    ).toHaveLength(2);
    expect(positionsOf({ type: 'Polygon', coordinates: [SQUARE] })).toHaveLength(5);
    expect(positionsOf({ type: 'MultiPolygon', coordinates: [[SQUARE], [SQUARE]] })).toHaveLength(10);
    expect(
      positionsOf({ type: 'MultiLineString', coordinates: [[HABARANA, [80.76, 8.04]]] }),
    ).toHaveLength(2);
    expect(positionsOf({ type: 'MultiPoint', coordinates: [HABARANA] })).toHaveLength(1);
  });
});

describe('bounds', () => {
  it('measures a geometry and a set of geometries', () => {
    expect(boundsOf({ type: 'Polygon', coordinates: [SQUARE] })).toEqual([80.7, 8.0, 80.8, 8.1]);
    const geometries: Geometry[] = [
      { type: 'Point', coordinates: [80.6, 7.9] },
      { type: 'Polygon', coordinates: [SQUARE] },
    ];
    expect(boundsOfGeometries(geometries)).toEqual([80.6, 7.9, 80.8, 8.1]);
  });

  it('has no bounds without positions', () => {
    expect(boundsOfPositions([])).toBeNull();
    expect(boundsOfGeometries([])).toBeNull();
  });

  it('pads by a fraction and never by nothing', () => {
    expect(padBounds([80.7, 8.0, 80.8, 8.1], 0.1)).toEqual([80.69, 7.99, 80.81, 8.11]);
    const [minLon, , maxLon] = padBounds([80.7, 8.0, 80.7, 8.0], 0.1);
    expect(maxLon - minLon).toBeCloseTo(0.001, 9);
  });

  it('answers containment, overlap and intersection', () => {
    const outer: Bounds = [80.0, 7.0, 81.0, 9.0];
    expect(boundsContain(outer, [80.5, 8.0, 80.6, 8.1])).toBe(true);
    expect(boundsContain(outer, [80.5, 8.0, 81.5, 8.1])).toBe(false);
    expect(boundsIntersect(outer, [80.9, 8.9, 82.0, 10.0])).toBe(true);
    expect(boundsIntersect(outer, [81.5, 8.0, 82.0, 9.0])).toBe(false);
    expect(intersectBounds(outer, [80.5, 8.0, 82.0, 10.0])).toEqual([80.5, 8.0, 81.0, 9.0]);
    expect(intersectBounds(outer, [81.5, 8.0, 82.0, 9.0])).toBeNull();
    expect(boundsContainPosition(outer, [80.5, 8.0])).toBe(true);
    expect(boundsContainPosition(outer, [79.5, 8.0])).toBe(false);
  });

  it('renders the API bbox parameter with six decimals', () => {
    expect(boundsToParameter([80.60000004, 7.9, 80.9, 8.2])).toBe('80.6,7.9,80.9,8.2');
    expect(boundsToParameter([80.1234567, 7.9, 80.9, 8.2]).split(',')[0]).toBe('80.123457');
  });
});

describe('containment', () => {
  it('counts the boundary as inside, like the API does', () => {
    expect(pointInRing([80.75, 8.05], SQUARE)).toBe(true);
    expect(pointInRing([80.7, 8.05], SQUARE)).toBe(true);
    expect(pointInRing([80.7, 8.0], SQUARE)).toBe(true);
    expect(pointInRing([80.9, 8.05], SQUARE)).toBe(false);
  });

  it('excludes holes but keeps their boundary inside', () => {
    const hole: Ring = [
      [80.74, 8.04],
      [80.76, 8.04],
      [80.76, 8.06],
      [80.74, 8.06],
      [80.74, 8.04],
    ];
    expect(pointInPolygon([80.75, 8.05], [SQUARE, hole])).toBe(false);
    expect(pointInPolygon([80.74, 8.05], [SQUARE, hole])).toBe(true);
    expect(pointInPolygon([80.72, 8.02], [SQUARE, hole])).toBe(true);
  });

  it('treats points and lines as containing nothing', () => {
    expect(pointInGeometry([80.75, 8.05], { type: 'Polygon', coordinates: [SQUARE] })).toBe(true);
    expect(
      pointInGeometry([80.75, 8.05], { type: 'MultiPolygon', coordinates: [[SQUARE]] }),
    ).toBe(true);
    expect(pointInGeometry([80.75, 8.05], { type: 'Point', coordinates: [80.75, 8.05] })).toBe(false);
  });

  it('reports a geometry touching an area', () => {
    const area: Geometry = { type: 'Polygon', coordinates: [SQUARE] };
    expect(
      geometryTouchesArea({ type: 'LineString', coordinates: [[80.75, 8.05], [81.5, 8.05]] }, area),
    ).toBe(true);
    expect(
      geometryTouchesArea({ type: 'LineString', coordinates: [[81.2, 8.05], [81.5, 8.05]] }, area),
    ).toBe(false);
  });

  it('rejects an empty ring list', () => {
    expect(pointInPolygon([80.75, 8.05], [])).toBe(false);
  });
});

describe('ring validity', () => {
  it('recognises and closes rings', () => {
    expect(ringIsClosed(SQUARE)).toBe(true);
    const open: Ring = SQUARE.slice(0, -1);
    expect(ringIsClosed(open)).toBe(false);
    expect(closeRing(open)).toHaveLength(SQUARE.length);
    expect(closeRing(SQUARE)).toBe(SQUARE);
    expect(closeRing([])).toEqual([]);
  });

  it('finds a ring that crosses itself and leaves a simple one alone', () => {
    expect(ringSelfIntersects(SQUARE)).toBe(false);
    const bowTie: Ring = [
      [80.7, 8.0],
      [80.8, 8.1],
      [80.8, 8.0],
      [80.7, 8.1],
      [80.7, 8.0],
    ];
    expect(ringSelfIntersects(bowTie)).toBe(true);
  });
});

describe('area', () => {
  it('measures a square in square metres on the EPSG:5235 plane', () => {
    const width = distanceM([80.7, 8.0], [80.8, 8.0]);
    const height = distanceM([80.7, 8.0], [80.7, 8.1]);
    const area = areaM2({ type: 'Polygon', coordinates: [SQUARE] });
    // The square is not a rectangle on the plane, so compare within a tenth of a percent.
    expect(area / (width * height)).toBeCloseTo(1, 2);
  });

  it('subtracts holes and measures nothing for a point', () => {
    const hole: Ring = [
      [80.74, 8.04],
      [80.76, 8.04],
      [80.76, 8.06],
      [80.74, 8.06],
      [80.74, 8.04],
    ];
    const withHole = areaM2({ type: 'Polygon', coordinates: [SQUARE, hole] });
    const solid = areaM2({ type: 'Polygon', coordinates: [SQUARE] });
    const holeArea = areaM2({ type: 'Polygon', coordinates: [hole] });
    expect(withHole).toBeCloseTo(solid - holeArea, 3);
    expect(areaM2({ type: 'Point', coordinates: HABARANA })).toBe(0);
    expect(areaM2({ type: 'MultiPolygon', coordinates: [[SQUARE], [hole]] })).toBeCloseTo(
      solid + holeArea,
      3,
    );
  });

  it('signs a ring by its winding', () => {
    expect(signedRingAreaM2(SQUARE)).toBeGreaterThan(0);
    expect(signedRingAreaM2([...SQUARE].reverse())).toBeLessThan(0);
  });
});

describe('circlePolygon', () => {
  it('puts every vertex at the radius and closes the ring', () => {
    const circle = circlePolygon(HABARANA, 750);
    const ring = circle.coordinates[0] ?? [];
    expect(ring).toHaveLength(129);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
    for (const vertex of ring) {
      expect(distanceM(HABARANA, vertex)).toBeCloseTo(750, 2);
    }
  });

  it('has the area of a circle', () => {
    expect(areaM2(circlePolygon(HABARANA, 1000, 1024)) / (Math.PI * 1000 ** 2)).toBeCloseTo(1, 4);
  });

  it('never draws fewer than eight segments', () => {
    expect(circlePolygon(HABARANA, 100, 2).coordinates[0]).toHaveLength(9);
  });
});

describe('Web Mercator', () => {
  it('round-trips a position', () => {
    const [lon, lat] = fromWebMercator(toWebMercator(HABARANA));
    expect(lon).toBeCloseTo(HABARANA[0], 9);
    expect(lat).toBeCloseTo(HABARANA[1], 9);
  });

  it('recovers the centre and radius of a ring drawn around a point', () => {
    // A Terra Draw circle: equal angles around the centre in Web Mercator.
    const [cx, cy] = toWebMercator(HABARANA);
    const radiusMercator = 1200;
    const drawn: Position[] = [];
    for (let index = 0; index < 64; index += 1) {
      const angle = (2 * Math.PI * index) / 64;
      drawn.push(
        fromWebMercator([cx + radiusMercator * Math.cos(angle), cy + radiusMercator * Math.sin(angle)]),
      );
    }
    const first = drawn[0];
    if (first === undefined) {
      throw new Error('the drawn ring is empty');
    }
    drawn.push(first);
    const centre = webMercatorCentre(drawn);
    if (centre === null) {
      throw new Error('a drawn ring has a centre');
    }
    expect(distanceM(centre, HABARANA)).toBeLessThan(0.01);
    const radius = meanRadiusM(centre, drawn);
    // Mercator metres are larger than ground metres away from the equator.
    expect(radius).toBeGreaterThan(1150);
    expect(radius).toBeLessThan(1200);
  });

  it('has no centre and no radius without positions', () => {
    expect(webMercatorCentre([])).toBeNull();
    expect(meanRadiusM(HABARANA, [])).toBe(0);
  });
});
