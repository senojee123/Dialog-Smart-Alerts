import { describe, expect, it } from 'vitest';

import { FEATURE_ID_PROPERTY } from '../sourceData';
import { geometryFilter, metresAsPixels, pointRadius, selectedFilter, selectedGeometryFilter } from './styles';

describe('filters', () => {
  it('matches the selected feature by the id the client added', () => {
    expect(selectedFilter('abc')).toEqual(['==', ['get', FEATURE_ID_PROPERTY], 'abc']);
  });

  it('matches nothing when nothing is selected', () => {
    const filter = selectedFilter(null) as unknown[];
    // Not the empty string: a feature really could have an empty property.
    expect(filter[2]).toBe('\u0000');
  });

  it('combines the selection with a geometry kind', () => {
    expect(selectedGeometryFilter('abc', 'Polygon')).toEqual([
      'all',
      ['==', ['get', FEATURE_ID_PROPERTY], 'abc'],
      ['==', ['geometry-type'], 'Polygon'],
    ]);
  });

  it('filters by geometry kind', () => {
    expect(geometryFilter('LineString')).toEqual(['==', ['geometry-type'], 'LineString']);
  });
});

describe('metresAsPixels', () => {
  it('doubles the pixel width for every zoom level', () => {
    const expression = metresAsPixels(1000, 8, 10, 20);
    const [, , , lowZoom, lowWidth, highZoom, highWidth] = expression as [
      string,
      unknown,
      unknown,
      number,
      number,
      number,
      number,
    ];
    expect(lowZoom).toBe(10);
    expect(highZoom).toBe(20);
    expect(highWidth / lowWidth).toBeCloseTo(2 ** 10, 6);
  });

  it('is the ground resolution at the given latitude', () => {
    const expression = metresAsPixels(1000, 0, 10, 20);
    const width = (expression as [string, unknown, unknown, number, number, number, number])[4];
    // At the equator, zoom 10: 156543.03392 / 2 * 2^-10 metres per pixel for 512 px tiles.
    const resolution = (156543.03392 * (256 / 512)) / 2 ** 10;
    expect(width).toBeCloseTo(1000 / resolution, 6);
  });
});

describe('pointRadius', () => {
  it('interpolates between two zooms', () => {
    expect(pointRadius(3, 7, 8, 15)).toEqual(['interpolate', ['linear'], ['zoom'], 8, 3, 15, 7]);
  });
});
