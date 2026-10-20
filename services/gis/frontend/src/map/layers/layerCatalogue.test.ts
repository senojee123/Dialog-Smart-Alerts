import { describe, expect, it } from 'vitest';

import {
  adminLevelForZoom,
  EVENT_LAYER_ID,
  FEATURE_LAYERS,
  LAYER_GROUPS,
  MAP_LAYERS,
  layerById,
} from './layerCatalogue';

describe('the layer catalogue', () => {
  it('gives every layer a unique id, a title and a legend', () => {
    const ids = MAP_LAYERS.map((layer) => layer.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const layer of MAP_LAYERS) {
      expect(layer.title).not.toBe('');
      expect(layer.description).not.toBe('');
      expect(layer.legend.length).toBeGreaterThan(0);
      expect(LAYER_GROUPS.map((group) => group.id)).toContain(layer.group);
    }
  });

  it('names layers by their code in the service registry', () => {
    for (const layer of FEATURE_LAYERS) {
      expect(layer.apiLayer).toMatch(/^(ref|ops)\.[a-z][a-z0-9_]+$/);
    }
  });

  it('keeps events out of the feature layers, because they have their own endpoint', () => {
    expect(FEATURE_LAYERS.some((layer) => layer.id === EVENT_LAYER_ID)).toBe(false);
    expect(layerById(EVENT_LAYER_ID)?.apiLayer).toBeNull();
  });

  it('draws areas before lines and points, and events last', () => {
    const order = MAP_LAYERS.map((layer) => layer.id);
    expect(order.indexOf('adminAreas')).toBeLessThan(order.indexOf('roads'));
    expect(order.indexOf('roads')).toBeLessThan(order.indexOf('settlements'));
    expect(order.indexOf('settlements')).toBeLessThan(order.indexOf('devices'));
    expect(order[order.length - 1]).toBe(EVENT_LAYER_ID);
  });

  it('knows nothing about a layer it does not have', () => {
    expect(layerById('ref.nonsense')).toBeUndefined();
  });
});

describe('administrative level by zoom', () => {
  it('shows provinces at country scale and divisions in a town', () => {
    expect(adminLevelForZoom(6)).toBe(1);
    expect(adminLevelForZoom(8)).toBe(2);
    expect(adminLevelForZoom(10)).toBe(3);
    expect(adminLevelForZoom(13)).toBe(4);
  });

  it('is what the administrative layer asks for', () => {
    const admin = layerById('adminAreas');
    expect(admin?.request?.(6)).toEqual({ filters: { level: 1 } });
    expect(admin?.request?.(13)).toEqual({ filters: { level: 4 } });
  });
});
