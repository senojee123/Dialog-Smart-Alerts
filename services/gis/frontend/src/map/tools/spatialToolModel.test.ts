import { describe, expect, it } from 'vitest';

import { deviceFeature, layerCatalogue, settlementFeature } from '../../test/fixtures';
import { featureCollection } from '../../test/fixtures';
import {
  cumulativeLabels,
  defaultTarget,
  resultRows,
  targetsFor,
  TOOL_HINTS,
  TOOL_LABELS,
  totalLengthM,
} from './spatialToolModel';

describe('resultRows', () => {
  it('reads a name, a distance and something to identify the feature by', () => {
    const rows = resultRows(
      featureCollection([
        { ...settlementFeature, properties: { ...settlementFeature.properties, distanceM: 512.34 } },
        { ...deviceFeature, properties: { ...deviceFeature.properties, relation: 'within' } },
      ]),
    );
    expect(rows[0]).toMatchObject({ name: 'Habarana', distanceM: 512.34, detail: 'town' });
    expect(rows[0]?.position).toEqual([80.7513, 8.0342]);
    expect(rows[1]).toMatchObject({ name: 'HB-CAM-01', distanceM: null, relation: 'within', detail: 'camera' });
  });

  it('falls back to the feature id when there is no name', () => {
    const rows = resultRows(featureCollection([{ ...settlementFeature, properties: {} }]));
    expect(rows[0]?.name).toBe(settlementFeature.id);
    expect(rows[0]?.detail).toBeNull();
  });

  it('has no position for a feature without geometry', () => {
    const rows = resultRows(featureCollection([{ ...settlementFeature, geometry: null }]));
    expect(rows[0]?.position).toBeNull();
  });
});

describe('the ruler', () => {
  it('labels the start and the running distance', () => {
    const labels = cumulativeLabels([
      [80.75, 8.03],
      [80.76, 8.03],
    ]);
    expect(labels[0]).toBe('start');
    expect(labels[1]).toMatch(/km|m$/);
  });

  it('measures the whole path', () => {
    expect(
      totalLengthM([
        [80.75, 8.03],
        [80.76, 8.03],
      ]),
    ).toBeGreaterThan(1000);
    expect(totalLengthM([])).toBe(0);
  });
});

describe('targets', () => {
  it('offers the layers the service says can answer the query', () => {
    expect(targetsFor(layerCatalogue, 'contains').map((layer) => layer.code)).toEqual([
      'ref.admin_area',
      'ref.water_body',
      'ref.protected_area',
      'ops.geofence',
      'ops.device_field_of_view',
    ]);
    expect(targetsFor(layerCatalogue, 'within_distance')).toHaveLength(layerCatalogue.layers.length);
    expect(targetsFor(null, 'nearest')).toEqual([]);
  });

  it('searches for something a distance search makes sense for', () => {
    // No facilities in this deployment, so settlements are what a radius search starts with - not the
    // administrative areas, which happen to be first in the catalogue.
    expect(defaultTarget(layerCatalogue)).toBe('ref.settlement');
    expect(defaultTarget({ layers: [], refDataRelease: null, attribution: [] })).toBe('ref.settlement');
    expect(defaultTarget(null)).toBe('ref.settlement');
  });
});

describe('the tools themselves', () => {
  it('names and explains every tool', () => {
    for (const tool of ['radius', 'nearby', 'measure', 'filter'] as const) {
      expect(TOOL_LABELS[tool]).not.toBe('');
      expect(TOOL_HINTS[tool]).not.toBe('');
    }
  });
});
