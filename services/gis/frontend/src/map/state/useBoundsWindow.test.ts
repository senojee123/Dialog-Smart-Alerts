import { act } from 'react';
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_DELAY_MS, needsNewWindow, useBoundsWindow, windowFor, type Viewport } from './useBoundsWindow';

const VIEWPORT: Viewport = { bounds: [80.7, 8.0, 80.8, 8.1], zoom: 12 };

describe('needsNewWindow', () => {
  it('needs one when there is none', () => {
    expect(needsNewWindow(null, VIEWPORT)).toBe(true);
  });

  it('does not need one while the viewport is inside what was asked for', () => {
    const current = windowFor(VIEWPORT);
    expect(needsNewWindow(current, VIEWPORT)).toBe(false);
    expect(needsNewWindow(current, { ...VIEWPORT, bounds: [80.71, 8.01, 80.79, 8.09] })).toBe(false);
  });

  it('needs one when the viewport leaves the window or the zoom level changes', () => {
    const current = windowFor(VIEWPORT);
    expect(needsNewWindow(current, { ...VIEWPORT, bounds: [81.5, 8.0, 81.6, 8.1] })).toBe(true);
    expect(needsNewWindow(current, { ...VIEWPORT, zoom: 13 })).toBe(true);
    expect(needsNewWindow(current, { ...VIEWPORT, zoom: 12.4 })).toBe(false);
  });

  it('pads the viewport it asks for', () => {
    const window = windowFor(VIEWPORT, 0.25);
    expect(window.bounds[0]).toBeLessThan(VIEWPORT.bounds[0]);
    expect(window.bounds[2]).toBeGreaterThan(VIEWPORT.bounds[2]);
    expect(window.zoom).toBe(12);
  });
});

describe('useBoundsWindow', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('has no window before the map has moved', () => {
    const { result } = renderHook(() => useBoundsWindow(null));
    expect(result.current).toBeNull();
  });

  it('waits out the pan before asking for a window', () => {
    const { result, rerender } = renderHook(({ viewport }) => useBoundsWindow(viewport), {
      initialProps: { viewport: VIEWPORT as Viewport | null },
    });
    expect(result.current).toBeNull();
    act(() => {
      vi.advanceTimersByTime(DEFAULT_DELAY_MS);
    });
    const first = result.current;
    expect(first).not.toBeNull();

    // A small pan stays inside the window, so nothing is asked for again.
    rerender({ viewport: { ...VIEWPORT, bounds: [80.705, 8.005, 80.805, 8.105] } });
    act(() => {
      vi.advanceTimersByTime(DEFAULT_DELAY_MS);
    });
    expect(result.current).toBe(first);

    // A long pan leaves it, and a new window is asked for.
    rerender({ viewport: { ...VIEWPORT, bounds: [81.4, 8.0, 81.5, 8.1] } });
    act(() => {
      vi.advanceTimersByTime(DEFAULT_DELAY_MS);
    });
    expect(result.current).not.toBe(first);
  });
});
