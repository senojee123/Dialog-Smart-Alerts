import { describe, expect, it, vi } from 'vitest';

vi.mock('maplibre-gl', () => ({ setWorkerUrl: vi.fn(), addProtocol: vi.fn() }));
vi.mock('maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url', () => ({ default: '/assets/maplibre-worker.js' }));

describe('MapLibre setup', () => {
  it('registers the worker and the pmtiles protocol exactly once', async () => {
    const maplibre = await import('maplibre-gl');
    const { configureMapLibre } = await import('./maplibreSetup');
    configureMapLibre();
    configureMapLibre();
    expect(maplibre.setWorkerUrl).toHaveBeenCalledExactlyOnceWith('/assets/maplibre-worker.js');
    expect(maplibre.addProtocol).toHaveBeenCalledExactlyOnceWith('pmtiles', expect.any(Function));
  });

  it('reports missing WebGL2 support', async () => {
    const { supportsWebGL2 } = await import('./maplibreSetup');
    const fakeDocument = {
      createElement: () => ({ getContext: () => null }),
    } as unknown as Document;
    expect(supportsWebGL2(fakeDocument)).toBe(false);
  });
});
