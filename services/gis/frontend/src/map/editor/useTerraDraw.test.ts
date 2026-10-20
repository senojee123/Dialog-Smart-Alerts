/**
 * The hook's side of Terra Draw: how changes are reported, and that a replaced map style gets a new
 * instance. Terra Draw itself is replaced by a recording stand-in; the browser tests drive the real one.
 */
import { act, renderHook } from '@testing-library/react';
import type { Map as MapLibreMap } from 'maplibre-gl';
import { beforeEach, describe, expect, it, vi } from 'vitest';

type Listener = (...args: unknown[]) => void;

const terra = vi.hoisted(() => ({
  instances: [] as {
    listeners: Map<string, (...args: unknown[]) => void>;
    stopped: boolean;
    mode: string;
    features: Map<string, unknown>;
  }[],
  /** The sources the fake map has; the stand-in adds the adapter's when it starts. */
  sources: new Set<string>(),
  /** Whether the next `start` fails, as it does on a style that has not finished loading. */
  failNextStart: false,
}));

vi.mock('terra-draw', () => {
  class Mode {
    readonly options: unknown;
    constructor(options?: unknown) {
      this.options = options;
    }
  }
  class TerraDraw {
    readonly record = {
      listeners: new Map<string, (...args: unknown[]) => void>(),
      stopped: false,
      mode: 'static',
      features: new Map<string, unknown>(),
    };
    constructor() {
      terra.instances.push(this.record);
    }
    on(event: string, listener: (...args: unknown[]) => void) {
      this.record.listeners.set(event, listener);
    }
    off(event: string) {
      this.record.listeners.delete(event);
    }
    start() {
      if (terra.failNextStart) {
        terra.failNextStart = false;
        throw new Error('Style is not done loading.');
      }
      terra.sources.add('td-polygon');
    }
    stop() {
      this.record.stopped = true;
    }
    setMode(mode: string) {
      this.record.mode = mode;
    }
    clear() {
      this.record.features.clear();
    }
    getSnapshot() {
      return [];
    }
    getSnapshotFeature(id: string) {
      return this.record.features.get(id);
    }
    addFeatures() {
      return [];
    }
    removeFeatures(ids: readonly string[]) {
      for (const id of ids) {
        this.record.features.delete(id);
      }
    }
  }
  return {
    TerraDraw,
    TerraDrawCircleMode: Mode,
    TerraDrawLineStringMode: Mode,
    TerraDrawPolygonMode: Mode,
    TerraDrawSelectMode: Mode,
  };
});

vi.mock('terra-draw-maplibre-gl-adapter', () => ({
  TerraDrawMapLibreGLAdapter: class {
    readonly options: unknown;
    constructor(options: unknown) {
      this.options = options;
    }
  },
}));

import { useTerraDraw } from './useTerraDraw';

function fakeMap() {
  const listeners = new Map<string, Set<Listener>>();
  const map = {
    on: (event: string, listener: Listener) => {
      const set = listeners.get(event) ?? new Set<Listener>();
      set.add(listener);
      listeners.set(event, set);
    },
    off: (event: string, listener: Listener) => {
      listeners.get(event)?.delete(listener);
    },
    getSource: (id: string) => (terra.sources.has(id) ? {} : undefined),
  };
  const fire = (event: string) => {
    for (const listener of listeners.get(event) ?? []) {
      listener();
    }
  };
  return { map: map as unknown as MapLibreMap, fire };
}

const SQUARE = {
  type: 'Polygon',
  coordinates: [
    [
      [80.74, 8.02],
      [80.78, 8.02],
      [80.78, 8.05],
      [80.74, 8.02],
    ],
  ],
};

beforeEach(() => {
  terra.instances.length = 0;
  terra.sources.clear();
  terra.failNextStart = false;
});

describe('useTerraDraw', () => {
  it('reports every feature a change names, and a deletion as no shape', () => {
    const { map } = fakeMap();
    const onChange = vi.fn();
    renderHook(() => useTerraDraw({ map, enabled: true, onFinish: vi.fn(), onChange }));
    const instance = terra.instances[0];
    expect(instance).toBeDefined();
    instance?.features.set('shape-1', { id: 'shape-1', geometry: SQUARE, properties: {} });
    const change = instance?.listeners.get('change');
    act(() => {
      change?.(['shape-1'], 'update');
      // Deselecting removes the handles select mode added: several features, none of them the shape.
      change?.(['handle-1', 'handle-2'], 'delete');
      change?.(['shape-1'], 'create');
    });
    expect(onChange.mock.calls).toEqual([
      ['shape-1', { id: 'shape-1', geometry: SQUARE, properties: {} }, 'geofence'],
      ['handle-1', null, 'geofence'],
      ['handle-2', null, 'geofence'],
    ]);
  });

  it('starts a new instance when a new map style has removed the old one', () => {
    const { map, fire } = fakeMap();
    const { result } = renderHook(() => useTerraDraw({ map, enabled: true, onFinish: vi.fn() }));
    expect(result.current.ready).toBe(true);
    // A style event while Terra Draw's sources are in place changes nothing.
    act(() => {
      fire('styledata');
    });
    expect(terra.instances).toHaveLength(1);
    // Switching the basemap replaces the style, and the adapter's sources go with it.
    terra.sources.clear();
    act(() => {
      fire('styledata');
    });
    expect(terra.instances).toHaveLength(2);
    expect(terra.instances[0]?.stopped).toBe(true);
    expect(terra.instances[1]?.stopped).toBe(false);
    expect(result.current.ready).toBe(true);
  });

  it('tries again when the new style was not ready for it', () => {
    const { map, fire } = fakeMap();
    const { result } = renderHook(() => useTerraDraw({ map, enabled: true, onFinish: vi.fn() }));
    terra.sources.clear();
    terra.failNextStart = true;
    act(() => {
      fire('styledata');
    });
    expect(result.current.ready).toBe(false);
    act(() => {
      fire('styledata');
    });
    expect(result.current.ready).toBe(true);
    expect(terra.instances.at(-1)?.stopped).toBe(false);
  });
});
