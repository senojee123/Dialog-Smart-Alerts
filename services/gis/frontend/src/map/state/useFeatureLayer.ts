/**
 * Loading one layer's features for the current window.
 *
 * Every layer follows the same pattern: ask for the window, follow the cursor for a bounded number of
 * pages, keep what was shown while the next answer is in flight, and say plainly when the answer was cut
 * short. Paging is the service's keyset cursor, so the pages are one consistent result set - the cursor
 * must be passed back with every other parameter unchanged (see docs/api/spatial-queries.md).
 *
 * The state holds the answer and the request it belongs to; everything else is derived. "Loading" is an
 * answer that does not belong to the current request, so no render has to set state to say so.
 */
import { useEffect, useMemo, useState } from 'react';

import { intersectBounds, type Bounds } from '../../geo/geometry';
import type { GisApi, LayerFilters } from '../../services/gisApi';
import type { ApiFeature } from '../../types/api';
import type { MapLayerDefinition } from '../layers/layerCatalogue';
import type { BoundsWindow } from './useBoundsWindow';

export type LoadStatus = 'idle' | 'loading' | 'success' | 'error';

/** Why a layer is showing nothing, when that is a decision rather than an empty answer. */
export type SilentReason = 'zoom' | 'hidden' | 'outside' | 'waiting';

export interface LayerData {
  readonly status: LoadStatus;
  readonly features: readonly ApiFeature[];
  readonly error: Error | null;
  readonly refDataRelease: string | null;
  /** The page limit was reached: what is drawn is part of the answer, not all of it. */
  readonly truncated: boolean;
  readonly reason: SilentReason | null;
}

export const NO_FEATURES: readonly ApiFeature[] = [];

function silent(reason: SilentReason): LayerData {
  return {
    status: 'idle',
    features: NO_FEATURES,
    error: null,
    refDataRelease: null,
    truncated: false,
    reason,
  };
}

export interface FeatureLayerOptions {
  readonly api: GisApi;
  readonly layer: MapLayerDefinition;
  readonly window: BoundsWindow | null;
  readonly enabled: boolean;
  readonly tenantId?: string | null;
  readonly limit?: number;
  readonly maxPages?: number;
  /**
   * Requests are clipped to the service area; a bbox outside it is refused by the API. `undefined` means
   * the service area is not known yet, and the layer waits rather than asking for a wider box than it
   * needs; `null` means it could not be read, and the request goes out unclipped.
   */
  readonly serviceAreaBounds?: Bounds | null | undefined;
  /** An area the operator drew to filter by: its bounding box narrows the request as well. */
  readonly filterBounds?: Bounds | null;
  /** Extra attribute filters from the operator, on top of the layer's own. */
  readonly filters?: LayerFilters;
  /** Change to reload the layer without moving the map. */
  readonly refreshKey?: number;
}

interface Request {
  readonly layer: string;
  readonly bounds: Bounds;
  readonly filters: LayerFilters;
  readonly includeGeometry: boolean;
  readonly tenantId: string | null;
  readonly limit: number;
  readonly maxPages: number;
  readonly key: string;
}

interface Answer {
  readonly key: string;
  readonly features: readonly ApiFeature[];
  readonly refDataRelease: string | null;
  readonly truncated: boolean;
  readonly error: Error | null;
}

type Plan = { readonly request: Request; readonly reason: null } | { readonly request: null; readonly reason: SilentReason };

/** The request the current state calls for, or why there is none. */
export function planRequest(options: FeatureLayerOptions): Plan {
  const {
    layer,
    window: viewWindow,
    enabled,
    tenantId = null,
    limit = 500,
    maxPages = 4,
    serviceAreaBounds,
    filterBounds = null,
    filters,
    refreshKey = 0,
  } = options;

  if (!enabled || layer.apiLayer === null) {
    return { request: null, reason: 'hidden' };
  }
  if (viewWindow === null || serviceAreaBounds === undefined) {
    return { request: null, reason: 'waiting' };
  }
  if (viewWindow.zoom < layer.minZoom) {
    return { request: null, reason: 'zoom' };
  }
  const own = layer.request === undefined ? {} : layer.request(viewWindow.zoom);
  if (own === null) {
    return { request: null, reason: 'zoom' };
  }
  const bounds = clip(viewWindow.bounds, serviceAreaBounds, filterBounds);
  if (bounds === null) {
    return { request: null, reason: 'outside' };
  }
  const request = {
    layer: layer.apiLayer,
    bounds,
    filters: { ...own.filters, ...filters } as LayerFilters,
    includeGeometry: own.includeGeometry ?? true,
    tenantId,
    limit,
    maxPages,
  };
  return {
    request: {
      ...request,
      key: JSON.stringify([
        request.layer,
        request.bounds,
        request.filters,
        request.includeGeometry,
        request.tenantId,
        request.limit,
        request.maxPages,
        refreshKey,
      ]),
    },
    reason: null,
  };
}

/**
 * The box to ask for: the window, narrowed by the service area and by any area drawn to filter by.
 *
 * A box narrower than the six decimals the `bbox` parameter carries is no box at all - the API requires
 * `minLon < maxLon` - so it counts as "nothing to ask for" rather than as a request that would be refused.
 */
const SMALLEST_BOX_DEGREES = 1e-6;

function clip(window: Bounds, ...limits: readonly (Bounds | null)[]): Bounds | null {
  let bounds: Bounds | null = window;
  for (const limit of limits) {
    if (limit !== null && bounds !== null) {
      bounds = intersectBounds(bounds, limit);
    }
  }
  if (bounds === null) {
    return null;
  }
  const tooNarrow =
    bounds[2] - bounds[0] < SMALLEST_BOX_DEGREES || bounds[3] - bounds[1] < SMALLEST_BOX_DEGREES;
  return tooNarrow ? null : bounds;
}

async function fetchPages(
  api: GisApi,
  request: Request,
  signal: AbortSignal,
): Promise<Omit<Answer, 'key' | 'error'>> {
  const collected: ApiFeature[] = [];
  let cursor: string | null = null;
  let refDataRelease: string | null = null;
  let truncated = false;
  for (let page = 0; page < request.maxPages; page += 1) {
    const answer = await api.listFeatures(
      {
        layer: request.layer,
        bounds: request.bounds,
        filters: request.filters,
        includeGeometry: request.includeGeometry,
        tenantId: request.tenantId,
        limit: request.limit,
        cursor,
      },
      { signal },
    );
    collected.push(...answer.features);
    refDataRelease = answer.refDataRelease ?? refDataRelease;
    cursor = answer.nextCursor ?? null;
    if (cursor === null) {
      break;
    }
    truncated = page === request.maxPages - 1;
  }
  return { features: collected, refDataRelease, truncated };
}

export function useFeatureLayer(options: FeatureLayerOptions): LayerData {
  const { api } = options;
  const plan = planRequest(options);
  const request = plan.request;
  const reason = plan.reason;
  const key = request?.key ?? '';
  const [answer, setAnswer] = useState<Answer | null>(null);

  useEffect(() => {
    if (request === null) {
      return;
    }
    const controller = new AbortController();
    fetchPages(api, request, controller.signal).then(
      (loaded) => {
        if (!controller.signal.aborted) {
          setAnswer({ key: request.key, ...loaded, error: null });
        }
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setAnswer({
          key: request.key,
          features: NO_FEATURES,
          refDataRelease: null,
          truncated: false,
          error: error instanceof Error ? error : new Error(String(error)),
        });
      },
    );
    return () => {
      controller.abort();
    };
    // The request *is* the dependency; `key` is its identity, and the object is rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key]);

  return useMemo(() => {
    if (reason !== null) {
      return silent(reason);
    }
    if (answer === null) {
      return {
        status: 'loading' as const,
        features: NO_FEATURES,
        error: null,
        refDataRelease: null,
        truncated: false,
        reason: null,
      };
    }
    if (answer.key !== key) {
      // The window moved: what was loaded stays on the map until the next answer arrives.
      return {
        status: 'loading' as const,
        features: answer.features,
        error: null,
        refDataRelease: answer.refDataRelease,
        truncated: answer.truncated,
        reason: null,
      };
    }
    return {
      status: answer.error === null ? ('success' as const) : ('error' as const),
      features: answer.features,
      error: answer.error,
      refDataRelease: answer.refDataRelease,
      truncated: answer.truncated,
      reason: null,
    };
  }, [answer, key, reason]);
}
