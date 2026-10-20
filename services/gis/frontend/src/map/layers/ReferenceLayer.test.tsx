import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-map-gl/maplibre', async () => (await import('../../test/reactMapGl')).mapGlMock());

import { mapState, resetMapState } from '../../test/reactMapGl';
import { MAP_LAYERS } from './layerCatalogue';
import { ReferenceLayer } from './ReferenceLayer';

const REFERENCE_LAYERS = MAP_LAYERS.filter((layer) => layer.group === 'reference');

beforeEach(() => {
  resetMapState();
});

describe('ReferenceLayer', () => {
  it.each(REFERENCE_LAYERS.map((layer) => [layer.id, layer] as const))(
    'draws every style layer of %s from its source',
    (_id, definition) => {
      render(
        <ReferenceLayer definition={definition} features={[]} selectedFeatureId={null} showLabels />,
      );
      expect(mapState.layers.length).toBeGreaterThan(0);
      // MapLibre refuses a layer without a source; react-map-gl only passes it to direct children.
      for (const layer of mapState.layers) {
        expect(layer.source, layer.id).toBe(`${definition.id}-source`);
      }
    },
  );
});
