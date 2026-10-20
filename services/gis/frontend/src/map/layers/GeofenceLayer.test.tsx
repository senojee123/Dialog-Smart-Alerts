import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-map-gl/maplibre', async () => (await import('../../test/reactMapGl')).mapGlMock());

import { mapState, resetMapState } from '../../test/reactMapGl';
import type { ApiFeature } from '../../types/api';
import { GeofenceLayer } from './GeofenceLayer';

function fence(id: string, status: string): ApiFeature {
  return {
    type: 'Feature',
    id,
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [80.74, 8.02],
          [80.78, 8.02],
          [80.78, 8.05],
          [80.74, 8.02],
        ],
      ],
    },
    properties: { name: id, status },
  };
}

beforeEach(() => {
  resetMapState();
});

describe('GeofenceLayer', () => {
  it('draws current geofences and leaves archived ones off the map', () => {
    render(
      <GeofenceLayer
        features={[fence('active-1', 'active'), fence('draft-1', 'draft'), fence('old-1', 'archived')]}
        selectedFeatureId={null}
        showLabels={false}
      />,
    );
    const [source] = mapState.sources;
    const data = source?.data as { features: { properties: { name: string } }[] };
    expect(data.features.map((feature) => feature.properties.name)).toEqual(['active-1', 'draft-1']);
    for (const layer of mapState.layers) {
      expect(layer.source, layer.id).toBe('geofences-source');
    }
  });
});
