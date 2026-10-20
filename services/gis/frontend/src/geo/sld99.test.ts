import { describe, expect, it } from 'vitest';

import { distanceM, metresPerDegree, pathLengthM, toMetric, toWgs84, type Position } from './sld99';
import { SLD99_REFERENCE } from './sld99Reference.generated';

/**
 * The reference values come from PROJ itself (`python -m app.tools.export_crs_reference`), so these
 * tests measure the client's transformation against the definition the service uses, not against
 * itself. A millimetre is far below the 0.01 m the API rounds distances to.
 */
const PROJECTION_TOLERANCE_M = 0.002;
const DISTANCE_TOLERANCE_M = 0.005;
const ROUND_TRIP_TOLERANCE_M = 0.005;

describe('EPSG:5235 projection', () => {
  it('reproduces every reference point PROJ computed', () => {
    const errors = SLD99_REFERENCE.points.map((point) => {
      const [easting, northing] = toMetric([point.lon, point.lat]);
      return {
        at: `${point.lon},${point.lat}`,
        error: Math.hypot(easting - point.easting, northing - point.northing),
      };
    });
    const worst = errors.reduce((a, b) => (a.error > b.error ? a : b));
    expect(worst.error, `worst point ${worst.at}`).toBeLessThan(PROJECTION_TOLERANCE_M);
  });

  it('carries the datum change rather than treating SLD99 as WGS84', () => {
    // The grid's natural origin is an SLD99 position. A WGS84 position of the same numbers is a
    // different place on the ground, a couple of hundred metres from the false origin.
    const [easting, northing] = toMetric([80.7717130833333, 7.00047152777778]);
    const offset = Math.hypot(easting - 500_000, northing - 500_000);
    expect(offset).toBeGreaterThan(100);
    expect(offset).toBeLessThan(400);
  });

  it('returns to the position it started from', () => {
    for (const point of SLD99_REFERENCE.points) {
      const original: Position = [point.lon, point.lat];
      expect(distanceM(original, toWgs84(toMetric(original)))).toBeLessThan(ROUND_TRIP_TOLERANCE_M);
    }
  });

  it('inverts the reference eastings and northings PROJ computed', () => {
    for (const point of SLD99_REFERENCE.points) {
      const recovered = toWgs84([point.easting, point.northing]);
      expect(distanceM([point.lon, point.lat], recovered)).toBeLessThan(ROUND_TRIP_TOLERANCE_M);
    }
  });
});

describe('distanceM', () => {
  it('matches the distances PROJ computed, short and long', () => {
    for (const pair of SLD99_REFERENCE.distances) {
      const from: Position = [pair.from[0], pair.from[1]];
      const to: Position = [pair.to[0], pair.to[1]];
      expect(Math.abs(distanceM(from, to) - pair.distanceM)).toBeLessThan(DISTANCE_TOLERANCE_M);
    }
  });

  it('is symmetric and zero for one point', () => {
    const a: Position = [80.7513, 8.0342];
    const b: Position = [80.7558, 8.0387];
    expect(distanceM(a, b)).toBeCloseTo(distanceM(b, a), 9);
    expect(distanceM(a, a)).toBe(0);
  });
});

describe('pathLengthM', () => {
  it('adds the legs of a path', () => {
    const start: Position = [80.75, 8.03];
    const corner: Position = [80.76, 8.03];
    const end: Position = [80.76, 8.04];
    const legs = distanceM(start, corner) + distanceM(corner, end);
    expect(pathLengthM([start, corner, end])).toBeCloseTo(legs, 6);
  });

  it('measures zero for fewer than two positions', () => {
    expect(pathLengthM([])).toBe(0);
    expect(pathLengthM([[80.75, 8.03]])).toBe(0);
  });
});

describe('metresPerDegree', () => {
  it('is about 110 km per degree of latitude and less per degree of longitude', () => {
    const scale = metresPerDegree([80.75, 8.03]);
    expect(scale.lat).toBeGreaterThan(110_000);
    expect(scale.lat).toBeLessThan(111_500);
    expect(scale.lon).toBeGreaterThan(109_000);
    expect(scale.lon).toBeLessThan(110_500);
  });
});
