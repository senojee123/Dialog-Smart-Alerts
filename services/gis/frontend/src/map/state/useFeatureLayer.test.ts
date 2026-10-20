import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { apiStub } from '../../test/apiStub';
import { featureCollection, settlementFeature } from '../../test/fixtures';
import { layerById, type MapLayerDefinition } from '../layers/layerCatalogue';
import { planRequest, useFeatureLayer } from './useFeatureLayer';
import type { BoundsWindow } from './useBoundsWindow';

const SETTLEMENTS = layerById('settlements') as MapLayerDefinition;
const ADMIN = layerById('adminAreas') as MapLayerDefinition;
const WINDOW: BoundsWindow = { bounds: [80.6, 7.9, 80.9, 8.2], zoom: 12 };
const SERVICE_AREA = [79.44, 5.66, 82.15, 10.08] as const;

function options(overrides: Record<string, unknown> = {}) {
  return {
    api: apiStub(),
    layer: SETTLEMENTS,
    window: WINDOW,
    enabled: true,
    serviceAreaBounds: SERVICE_AREA,
    ...overrides,
  } as Parameters<typeof useFeatureLayer>[0];
}

describe('planRequest', () => {
  it('asks for nothing while the layer is hidden', () => {
    expect(planRequest(options({ enabled: false })).reason).toBe('hidden');
  });

  it('asks for nothing before the map has a window', () => {
    expect(planRequest(options({ window: null })).reason).toBe('waiting');
  });

  it('asks for nothing below the minimum zoom of the layer', () => {
    expect(planRequest(options({ window: { ...WINDOW, zoom: 5 } })).reason).toBe('zoom');
  });

  it('asks for nothing when the window does not overlap the service area', () => {
    expect(
      planRequest(options({ window: { bounds: [100, 12, 101, 13], zoom: 12 } })).reason,
    ).toBe('outside');
  });

  it('clips the window to the service area', () => {
    const plan = planRequest(options({ window: { bounds: [78, 4, 81, 9], zoom: 12 } }));
    expect(plan.request?.bounds).toEqual([79.44, 5.66, 81, 9]);
  });

  it('merges the filters of the operator over those of the layer', () => {
    const plan = planRequest(
      options({ layer: ADMIN, window: { ...WINDOW, zoom: 6 }, filters: { code: 'LK7' } }),
    );
    expect(plan.request?.filters).toEqual({ level: 1, code: 'LK7' });
  });

  it('gives the same request the same identity, and a different one a new identity', () => {
    const first = planRequest(options());
    const same = planRequest(options());
    const other = planRequest(options({ refreshKey: 1 }));
    expect(first.request?.key).toBe(same.request?.key);
    expect(first.request?.key).not.toBe(other.request?.key);
  });
});

describe('useFeatureLayer', () => {
  it('loads the window and reports what it found', async () => {
    const api = apiStub({
      listFeatures: vi.fn(() => Promise.resolve(featureCollection([settlementFeature]))),
    });
    const { result } = renderHook(() => useFeatureLayer(options({ api })));
    expect(result.current.status).toBe('loading');
    await waitFor(() => {
      expect(result.current.status).toBe('success');
    });
    expect(result.current.features).toHaveLength(1);
    expect(result.current.refDataRelease).toBe('ref-2026.09-lka-open');
    expect(result.current.truncated).toBe(false);
    expect(api.listFeatures).toHaveBeenCalledWith(
      expect.objectContaining({ layer: 'ref.settlement', bounds: [80.6, 7.9, 80.9, 8.2], cursor: null }),
      expect.objectContaining({ signal: expect.anything() }),
    );
  });

  it('follows the cursor and says when it stopped following it', async () => {
    const api = apiStub({
      listFeatures: vi.fn(() =>
        Promise.resolve(featureCollection([settlementFeature], { nextCursor: 'more' })),
      ),
    });
    const { result } = renderHook(() => useFeatureLayer(options({ api, maxPages: 2 })));
    await waitFor(() => {
      expect(result.current.status).toBe('success');
    });
    expect(api.listFeatures).toHaveBeenCalledTimes(2);
    expect(result.current.features).toHaveLength(2);
    expect(result.current.truncated).toBe(true);
  });

  it('keeps showing what it had while the next window loads', async () => {
    const api = apiStub({
      listFeatures: vi.fn(() => Promise.resolve(featureCollection([settlementFeature]))),
    });
    const { result, rerender } = renderHook(
      (props: { window: BoundsWindow }) => useFeatureLayer(options({ api, window: props.window })),
      { initialProps: { window: WINDOW } },
    );
    await waitFor(() => {
      expect(result.current.status).toBe('success');
    });
    rerender({ window: { bounds: [81.0, 8.0, 81.3, 8.3], zoom: 12 } });
    expect(result.current.status).toBe('loading');
    expect(result.current.features).toHaveLength(1);
    await waitFor(() => {
      expect(result.current.status).toBe('success');
    });
  });

  it('does not reload when the zoom changes but the request does not', async () => {
    const api = apiStub({
      listFeatures: vi.fn(() => Promise.resolve(featureCollection([settlementFeature]))),
    });
    const { result, rerender } = renderHook(
      (props: { zoom: number }) =>
        useFeatureLayer(options({ api, window: { ...WINDOW, zoom: props.zoom } })),
      { initialProps: { zoom: 12 } },
    );
    await waitFor(() => {
      expect(result.current.status).toBe('success');
    });
    rerender({ zoom: 13 });
    expect(result.current.status).toBe('success');
    expect(api.listFeatures).toHaveBeenCalledTimes(1);
  });

  it('reports a failure without losing the reason', async () => {
    const api = apiStub({ listFeatures: vi.fn(() => Promise.reject(new Error('gateway timeout'))) });
    const { result } = renderHook(() => useFeatureLayer(options({ api })));
    await waitFor(() => {
      expect(result.current.status).toBe('error');
    });
    expect(result.current.error?.message).toBe('gateway timeout');
    expect(result.current.features).toHaveLength(0);
  });

  it('asks for nothing at all while it is hidden', () => {
    const api = apiStub();
    const { result } = renderHook(() => useFeatureLayer(options({ api, enabled: false })));
    expect(result.current.reason).toBe('hidden');
    expect(api.listFeatures).not.toHaveBeenCalled();
  });
});
