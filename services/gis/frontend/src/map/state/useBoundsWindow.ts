/**
 * Which area the map asks the API about.
 *
 * Panning a map produces a viewport change per frame; asking the API per frame would be absurd. The
 * window is a padded box around the viewport, and it is replaced only when the viewport leaves it or
 * the zoom crosses an integer - a small pan is answered from what is already loaded.
 */
import { useEffect, useRef, useState } from 'react';

import { boundsContain, padBounds, type Bounds } from '../../geo/geometry';

export interface Viewport {
  readonly bounds: Bounds;
  readonly zoom: number;
}

export interface BoundsWindow {
  readonly bounds: Bounds;
  /** Zoom the window was requested at; layers whose detail depends on zoom use this one. */
  readonly zoom: number;
}

export const DEFAULT_PAD_FRACTION = 0.25;
export const DEFAULT_DELAY_MS = 250;

export function windowFor(viewport: Viewport, padFraction = DEFAULT_PAD_FRACTION): BoundsWindow {
  return { bounds: padBounds(viewport.bounds, padFraction), zoom: viewport.zoom };
}

/** A new window is needed when the viewport has left the loaded one or the zoom level has changed. */
export function needsNewWindow(current: BoundsWindow | null, viewport: Viewport): boolean {
  if (current === null) {
    return true;
  }
  if (Math.floor(current.zoom) !== Math.floor(viewport.zoom)) {
    return true;
  }
  return !boundsContain(current.bounds, viewport.bounds);
}

export interface BoundsWindowOptions {
  readonly padFraction?: number;
  readonly delayMs?: number;
}

/**
 * The window to request for the current viewport, updated at most once per `delayMs` and only when the
 * viewport actually needs more than what was asked for.
 */
export function useBoundsWindow(
  viewport: Viewport | null,
  options: BoundsWindowOptions = {},
): BoundsWindow | null {
  const { padFraction = DEFAULT_PAD_FRACTION, delayMs = DEFAULT_DELAY_MS } = options;
  const [requested, setRequested] = useState<BoundsWindow | null>(null);
  const requestedRef = useRef<BoundsWindow | null>(null);

  useEffect(() => {
    if (viewport === null || !needsNewWindow(requestedRef.current, viewport)) {
      return;
    }
    const timer = setTimeout(() => {
      const next = windowFor(viewport, padFraction);
      requestedRef.current = next;
      setRequested(next);
    }, delayMs);
    return () => {
      clearTimeout(timer);
    };
  }, [viewport, padFraction, delayMs]);

  return requested;
}
