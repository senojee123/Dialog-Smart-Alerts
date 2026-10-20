import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { apiStub } from '../../test/apiStub';
import { eventCollection, eventFeature } from '../../test/fixtures';
import { defaultEventFilters } from './mapState';
import { useEventLayer } from './useEventLayer';
import type { BoundsWindow } from './useBoundsWindow';

const WINDOW: BoundsWindow = { bounds: [80.6, 7.9, 80.9, 8.2], zoom: 12 };
const NOW = new Date('2026-09-15T12:00:00Z');

function options(overrides: Record<string, unknown> = {}) {
  return {
    api: apiStub({ listEvents: vi.fn(() => Promise.resolve(eventCollection([eventFeature]))) }),
    window: WINDOW,
    enabled: true,
    filters: defaultEventFilters(24),
    serviceAreaBounds: [79.44, 5.66, 82.15, 10.08],
    now: () => NOW,
    ...overrides,
  } as Parameters<typeof useEventLayer>[0];
}

describe('useEventLayer', () => {
  it('asks for the last 24 hours of the viewport and shows the window the service answered for', async () => {
    const opts = options();
    const { result } = renderHook(() => useEventLayer(opts));
    await waitFor(() => {
      expect(result.current.status).toBe('success');
    });
    expect(opts.api.listEvents).toHaveBeenCalledWith(
      expect.objectContaining({
        from: '2026-09-14T12:00:00.000Z',
        to: '2026-09-15T12:00:00.000Z',
        bounds: [80.6, 7.9, 80.9, 8.2],
      }),
      expect.anything(),
    );
    // The answer's own window is what the panel shows, not what was asked for.
    expect(result.current.window).toEqual({ from: '2026-09-14T00:00:00Z', to: '2026-09-15T00:00:00Z' });
    expect(result.current.features).toHaveLength(1);
    expect(result.current.loadedAt).toEqual(NOW);
  });

  it('passes the filters the operator set', async () => {
    const opts = options({
      filters: { ...defaultEventFilters(6), eventType: 'wildlife.elephant_detected', sourceType: 'sensor' },
    });
    renderHook(() => useEventLayer(opts));
    await waitFor(() => {
      expect(opts.api.listEvents).toHaveBeenCalled();
    });
    expect(opts.api.listEvents).toHaveBeenCalledWith(
      expect.objectContaining({
        eventType: 'wildlife.elephant_detected',
        sourceType: 'sensor',
        from: '2026-09-15T06:00:00.000Z',
      }),
      expect.anything(),
    );
  });

  it('asks for nothing while the layer is off', () => {
    const opts = options({ enabled: false });
    const { result } = renderHook(() => useEventLayer(opts));
    expect(result.current.reason).toBe('hidden');
    expect(opts.api.listEvents).not.toHaveBeenCalled();
  });

  it('asks for nothing when the viewport is outside the service area', () => {
    const opts = options({ window: { bounds: [100, 12, 101, 13], zoom: 12 } });
    const { result } = renderHook(() => useEventLayer(opts));
    expect(result.current.reason).toBe('outside');
    expect(opts.api.listEvents).not.toHaveBeenCalled();
  });

  it('waits for the service area rather than asking for a wider box than the API accepts', () => {
    const opts = options({ serviceAreaBounds: undefined });
    const { result } = renderHook(() => useEventLayer(opts));
    expect(result.current.reason).toBe('waiting');
    expect(opts.api.listEvents).not.toHaveBeenCalled();
  });

  it('narrows the request to an area the operator drew to filter by', async () => {
    const opts = options({ filterBounds: [80.7, 8.0, 80.8, 8.1] });
    renderHook(() => useEventLayer(opts));
    await waitFor(() => {
      expect(opts.api.listEvents).toHaveBeenCalled();
    });
    expect(opts.api.listEvents).toHaveBeenCalledWith(
      expect.objectContaining({ bounds: [80.7, 8.0, 80.8, 8.1] }),
      expect.anything(),
    );
  });

  it('reports a failure', async () => {
    const opts = options({ api: apiStub({ listEvents: vi.fn(() => Promise.reject(new Error('nope'))) }) });
    const { result } = renderHook(() => useEventLayer(opts));
    await waitFor(() => {
      expect(result.current.status).toBe('error');
    });
    expect(result.current.error?.message).toBe('nope');
  });
});
