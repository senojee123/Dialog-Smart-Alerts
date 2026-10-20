import { describe, expect, it } from 'vitest';

import { serviceArea } from '../test/fixtures';
import {
  bboxToBounds,
  NEUTRAL_STYLE,
  parseViewHash,
  resolveMapStyle,
  serviceAreaBounds,
  viewHash,
} from './mapStyle';

describe('map style', () => {
  it('falls back to the neutral style when no basemap is configured', () => {
    expect(resolveMapStyle(null)).toBe(NEUTRAL_STYLE);
    expect(NEUTRAL_STYLE.version).toBe(8);
  });

  it('uses the configured basemap style URL', () => {
    expect(resolveMapStyle('pmtiles-style.json')).toBe('pmtiles-style.json');
  });

  it('converts a WGS84 bbox into south-west / north-east bounds', () => {
    expect(bboxToBounds([79.44, 5.66, 82.15, 10.08])).toEqual([
      [79.44, 5.66],
      [82.15, 10.08],
    ]);
    expect(serviceAreaBounds(serviceArea)).toEqual([
      [79.44, 5.66],
      [82.15, 10.08],
    ]);
  });

  it('reads a linked view from the URL fragment, and nothing else', () => {
    expect(parseViewHash('#map=12.5/8.0423/80.7565')).toEqual({ zoom: 12.5, latitude: 8.0423, longitude: 80.7565 });
    expect(parseViewHash('#map=7/-33.9/151.2')).toEqual({ zoom: 7, latitude: -33.9, longitude: 151.2 });
    expect(parseViewHash('')).toBeNull();
    expect(parseViewHash('#12/8/80')).toBeNull();
    expect(parseViewHash('#map=12/95/80')).toBeNull();
    expect(parseViewHash('#map=30/8/80')).toBeNull();
    expect(parseViewHash('#map=12/8/80&layers=all')).toBeNull();
  });

  it('writes a view as a fragment that reads back the same', () => {
    const view = { zoom: 13.25, latitude: 8.04232, longitude: 80.75646 };
    expect(viewHash(view)).toBe('#map=13.25/8.04232/80.75646');
    expect(parseViewHash(viewHash(view))).toEqual(view);
  });
});
