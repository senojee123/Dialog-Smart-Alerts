import { describe, expect, it } from 'vitest';

import { deviceFeature, eventFeature, settlementFeature } from '../test/fixtures';
import type { ApiFeature, Geometry } from '../types/api';
import {
  EMPTY_COLLECTION,
  FEATURE_ID_PROPERTY,
  LAYER_ID_PROPERTY,
  featuresInArea,
  geometrySource,
  positionsSource,
  readGeometry,
  toSourceData,
} from './sourceData';

// Contains the settlement (80.7513, 8.0342) and the device (80.752, 8.04), but not the event
// (80.749, 8.037), which lies just west of it.
const AREA: Geometry = {
  type: 'Polygon',
  coordinates: [
    [
      [80.75, 8.03],
      [80.76, 8.03],
      [80.76, 8.045],
      [80.75, 8.045],
      [80.75, 8.03],
    ],
  ],
};

describe('toSourceData', () => {
  it('carries the feature id and the layer into the properties', () => {
    const data = toSourceData('settlements', [settlementFeature]);
    const feature = data.features[0];
    expect(feature?.properties[FEATURE_ID_PROPERTY]).toBe(settlementFeature.id);
    expect(feature?.properties[LAYER_ID_PROPERTY]).toBe('settlements');
    expect(feature?.properties.name).toBe('Habarana');
  });

  it('leaves out a feature whose geometry was not requested', () => {
    const withoutGeometry: ApiFeature = { ...settlementFeature, geometry: null };
    expect(toSourceData('settlements', [withoutGeometry]).features).toHaveLength(0);
  });

  it('adds what the paint expressions need but the API does not provide', () => {
    const data = toSourceData('devices', [deviceFeature], () => ({ _deviceState: 'offline' }));
    expect(data.features[0]?.properties._deviceState).toBe('offline');
  });
});

describe('geometrySource and positionsSource', () => {
  it('has no features for no geometry', () => {
    expect(geometrySource(null)).toEqual(EMPTY_COLLECTION);
  });

  it('wraps one geometry', () => {
    const data = geometrySource(AREA, { role: 'filter' });
    expect(data.features).toHaveLength(1);
    expect(data.features[0]?.properties.role).toBe('filter');
  });

  it('makes a point per position, with the properties it is given', () => {
    const data = positionsSource(
      [
        [80.75, 8.03],
        [80.76, 8.04],
      ],
      (_position, index) => ({ label: `p${index}` }),
    );
    expect(data.features).toHaveLength(2);
    expect(data.features[1]?.properties.label).toBe('p1');
    expect(data.features[1]?.geometry).toEqual({ type: 'Point', coordinates: [80.76, 8.04] });
  });
});

describe('featuresInArea', () => {
  it('keeps everything when nothing was drawn', () => {
    const features = [settlementFeature, deviceFeature];
    expect(featuresInArea(features, null)).toBe(features);
  });

  it('keeps what lies inside the drawn area', () => {
    const inside = featuresInArea([settlementFeature, deviceFeature, eventFeature], AREA);
    expect(inside.map((feature) => feature.id)).toEqual([settlementFeature.id, deviceFeature.id]);
  });

  it('drops a feature without geometry', () => {
    expect(featuresInArea([{ ...settlementFeature, geometry: null }], AREA)).toHaveLength(0);
  });
});

describe('readGeometry', () => {
  it('accepts the geometry MapLibre hands back', () => {
    expect(readGeometry({ type: 'Point', coordinates: [80.75, 8.03] })).toEqual({
      type: 'Point',
      coordinates: [80.75, 8.03],
    });
  });

  it('refuses anything else, including a GeometryCollection', () => {
    expect(readGeometry({ type: 'GeometryCollection', geometries: [] })).toBeNull();
    expect(readGeometry(null)).toBeNull();
    expect(readGeometry({ type: 'Point', coordinates: [500, 8] })).toBeNull();
  });
});
