import { act } from 'react';
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MAP_LAYERS } from '../layers/layerCatalogue';
import { defaultVisibleLayers, useLayerVisibility } from './useLayerVisibility';

describe('useLayerVisibility', () => {
  it('starts with the layers the catalogue shows by default', () => {
    const { result } = renderHook(() => useLayerVisibility());
    expect(result.current.visible).toEqual(defaultVisibleLayers());
    expect(result.current.isVisible('events')).toBe(true);
    expect(result.current.isVisible('facilities')).toBe(false);
  });

  it('toggles and sets one layer', () => {
    const { result } = renderHook(() => useLayerVisibility());
    act(() => {
      result.current.toggle('events');
    });
    expect(result.current.isVisible('events')).toBe(false);
    act(() => {
      result.current.set('events', true);
    });
    expect(result.current.isVisible('events')).toBe(true);
    act(() => {
      result.current.set('events', true);
    });
    expect(result.current.isVisible('events')).toBe(true);
  });

  it('turns a whole group on and off', () => {
    const { result } = renderHook(() => useLayerVisibility());
    act(() => {
      result.current.setGroup('reference', false);
    });
    const reference = MAP_LAYERS.filter((layer) => layer.group === 'reference');
    expect(reference.every((layer) => !result.current.isVisible(layer.id))).toBe(true);
    act(() => {
      result.current.setGroup('reference', true);
    });
    expect(reference.every((layer) => result.current.isVisible(layer.id))).toBe(true);
  });

  it('goes back to the defaults', () => {
    const { result } = renderHook(() => useLayerVisibility(new Set()));
    expect(result.current.visible.size).toBe(0);
    act(() => {
      result.current.reset();
    });
    expect(result.current.visible).toEqual(defaultVisibleLayers());
  });
});
