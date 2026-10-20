import { act } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../services/apiClient';
import { apiStub } from '../../test/apiStub';
import { deviceFeature, featureCollection, layerCatalogue, settlementFeature } from '../../test/fixtures';
import { useSpatialTools } from './useSpatialTools';

const POSITION = [80.7513, 8.0342] as const;

function setUp(api = apiStub()) {
  const hook = renderHook(() =>
    useSpatialTools({ api, tenantId: 'wildlife-dept', catalogue: layerCatalogue }),
  );
  return { api, ...hook };
}

describe('useSpatialTools', () => {
  it('starts with nothing armed and a target the catalogue offers', () => {
    const { result } = setUp();
    expect(result.current.tool).toBeNull();
    expect(result.current.target).toBe('ref.settlement');
    expect(result.current.circle).toBeNull();
    expect(result.current.stale).toBe(false);
  });

  it('follows the catalogue until the operator chooses a target', () => {
    const api = apiStub();
    const { result, rerender } = renderHook(
      (props: { catalogue: typeof layerCatalogue | null }) =>
        useSpatialTools({ api, tenantId: null, catalogue: props.catalogue }),
      { initialProps: { catalogue: null as typeof layerCatalogue | null } },
    );
    // Before the catalogue arrives there is nothing to choose from, so the fallback stands.
    expect(result.current.target).toBe('ref.settlement');
    const oneLayer = layerCatalogue.layers.filter((layer) => layer.code === 'ref.settlement');
    rerender({ catalogue: { layers: oneLayer, refDataRelease: null, attribution: [] } });
    expect(result.current.target).toBe('ref.settlement');
    act(() => {
      result.current.setTarget('ops.device');
    });
    expect(result.current.target).toBe('ops.device');
  });

  it('says its answer is stale when the distance or the layer changed since the search', async () => {
    const api = apiStub({
      queryWithinDistance: vi.fn(() => Promise.resolve(featureCollection([settlementFeature]))),
    });
    const { result } = setUp(api);
    act(() => {
      result.current.selectTool('radius');
    });
    act(() => {
      result.current.handleClick(POSITION);
    });
    await waitFor(() => {
      expect(result.current.status).toBe('done');
    });
    expect(result.current.stale).toBe(false);
    act(() => {
      result.current.setRadiusM(5000);
    });
    expect(result.current.stale).toBe(true);
    act(() => {
      result.current.rerun();
    });
    await waitFor(() => {
      expect(result.current.stale).toBe(false);
    });
    expect(api.queryWithinDistance).toHaveBeenLastCalledWith(
      expect.objectContaining({ distanceM: 5000 }),
      expect.anything(),
    );
  });

  it('runs a radius search where the operator clicked', async () => {
    const api = apiStub({
      queryWithinDistance: vi.fn(() => Promise.resolve(featureCollection([settlementFeature]))),
    });
    const { result } = setUp(api);
    act(() => {
      result.current.selectTool('radius');
    });
    act(() => {
      result.current.setRadiusM(2500);
    });
    act(() => {
      result.current.handleClick(POSITION);
    });
    await waitFor(() => {
      expect(result.current.status).toBe('done');
    });
    expect(api.queryWithinDistance).toHaveBeenCalledWith(
      expect.objectContaining({
        target: 'ref.settlement',
        distanceM: 2500,
        geometry: { type: 'Point', coordinates: POSITION },
        tenantId: 'wildlife-dept',
      }),
      expect.anything(),
    );
    expect(result.current.rows).toHaveLength(1);
    expect(result.current.circle).toEqual({ centre: POSITION, radiusM: 2500 });
  });

  it('finds the nearest devices, and asks the device layer for them', async () => {
    const api = apiStub({ queryNearest: vi.fn(() => Promise.resolve(featureCollection([deviceFeature]))) });
    const { result } = setUp(api);
    act(() => {
      result.current.selectTool('nearby');
    });
    act(() => {
      result.current.setNearestLimit(3);
    });
    act(() => {
      result.current.handleClick(POSITION);
    });
    await waitFor(() => {
      expect(result.current.status).toBe('done');
    });
    expect(api.queryNearest).toHaveBeenCalledWith(
      expect.objectContaining({ target: 'ops.device', limit: 3 }),
      expect.anything(),
    );
    // A nearest search is bounded, not drawn as a circle.
    expect(result.current.circle).toBeNull();
    expect(result.current.rows[0]?.name).toBe('HB-CAM-01');
  });

  it('collects and undoes the positions of the ruler', () => {
    const { result } = setUp();
    act(() => {
      result.current.selectTool('measure');
    });
    act(() => {
      result.current.handleClick(POSITION);
    });
    act(() => {
      result.current.handleClick([80.76, 8.04]);
    });
    expect(result.current.measure).toHaveLength(2);
    act(() => {
      result.current.undoMeasure();
    });
    expect(result.current.measure).toHaveLength(1);
    act(() => {
      result.current.clearResults();
    });
    expect(result.current.measure).toHaveLength(0);
  });

  it('forgets the ruler when another tool is armed', () => {
    const { result } = setUp();
    act(() => {
      result.current.selectTool('measure');
    });
    act(() => {
      result.current.handleClick(POSITION);
    });
    act(() => {
      result.current.selectTool('radius');
    });
    expect(result.current.measure).toHaveLength(0);
  });

  it('shows what the service said when a query is refused', async () => {
    const api = apiStub({
      queryWithinDistance: vi.fn(() =>
        Promise.reject(
          new ApiError('refused', {
            status: 422,
            problem: {
              type: 'urn:gis-core-service:problem:unsupported_filter',
              title: 'Filter not supported',
              status: 422,
              detail: 'That layer has no such filter.',
            },
          }),
        ),
      ),
    });
    const { result } = setUp(api);
    act(() => {
      result.current.selectTool('radius');
    });
    act(() => {
      result.current.handleClick(POSITION);
    });
    await waitFor(() => {
      expect(result.current.status).toBe('error');
    });
    expect(result.current.error).toBe('That layer has no such filter. (unsupported_filter)');
    expect(result.current.rows).toHaveLength(0);
  });

  it('says when an answer was only the first page', async () => {
    const api = apiStub({
      queryWithinDistance: vi.fn(() =>
        Promise.resolve(featureCollection([settlementFeature], { nextCursor: 'more' })),
      ),
    });
    const { result } = setUp(api);
    act(() => {
      result.current.selectTool('radius');
    });
    act(() => {
      result.current.handleClick(POSITION);
    });
    await waitFor(() => {
      expect(result.current.truncated).toBe(true);
    });
  });

  it('ignores a click while no tool is armed', () => {
    const { api, result } = setUp();
    act(() => {
      result.current.handleClick(POSITION);
    });
    expect(api.queryWithinDistance).not.toHaveBeenCalled();
    expect(result.current.measure).toHaveLength(0);
  });
});
