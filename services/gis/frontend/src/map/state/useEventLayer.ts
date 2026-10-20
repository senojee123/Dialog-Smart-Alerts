/**
 * Loading event locations for the current window in space and in time.
 *
 * Events are not a layer like the others: they come from `GET /geo/v1/events`, they are bounded in time
 * as well as in space (the service refuses a window longer than 31 days, because event storage is
 * partitioned by month), and the answer echoes the window it used - which is what the map shows the
 * operator, rather than what was asked for.
 *
 * A relative window ("the last 24 hours") is resolved when the request is made, not while rendering, so
 * the clock cannot make the request look different on every render.
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import { intersectBounds, type Bounds } from '../../geo/geometry';
import type { GisApi } from '../../services/gisApi';
import type { ApiFeature } from '../../types/api';
import { eventWindow, type EventFilterState, type TimeWindow } from './mapState';
import type { BoundsWindow } from './useBoundsWindow';
import { NO_FEATURES, type LoadStatus } from './useFeatureLayer';

export interface EventLayerData {
  readonly status: LoadStatus;
  readonly features: readonly ApiFeature[];
  readonly error: Error | null;
  /** The window the service answered for. */
  readonly window: TimeWindow | null;
  readonly truncated: boolean;
  readonly reason: 'hidden' | 'outside' | 'waiting' | null;
  /** When the answer was received, so the operator can see how fresh it is. */
  readonly loadedAt: Date | null;
}

const IDLE: EventLayerData = {
  status: 'idle',
  features: NO_FEATURES,
  error: null,
  window: null,
  truncated: false,
  reason: null,
  loadedAt: null,
};

export interface EventLayerOptions {
  readonly api: GisApi;
  readonly window: BoundsWindow | null;
  readonly enabled: boolean;
  readonly filters: EventFilterState;
  readonly tenantId?: string | null;
  readonly limit?: number;
  readonly maxPages?: number;
  readonly serviceAreaBounds?: Bounds | null | undefined;
  /** An area the operator drew to filter by: its bounding box narrows the request as well. */
  readonly filterBounds?: Bounds | null;
  /** Re-read on this interval; `0` leaves it to the operator. */
  readonly refreshIntervalMs?: number;
  readonly refreshKey?: number;
  /** Injected in tests; the clock is what makes a relative window relative. */
  readonly now?: () => Date;
}

interface Answer {
  readonly key: string;
  readonly features: readonly ApiFeature[];
  readonly window: TimeWindow | null;
  readonly truncated: boolean;
  readonly error: Error | null;
  readonly loadedAt: Date;
}

function narrow(window: Bounds, ...limits: readonly (Bounds | null)[]): Bounds | null {
  let bounds: Bounds | null = window;
  for (const limit of limits) {
    if (limit !== null && bounds !== null) {
      bounds = intersectBounds(bounds, limit);
    }
  }
  return bounds;
}

export function useEventLayer(options: EventLayerOptions): EventLayerData {
  const {
    api,
    window: viewWindow,
    enabled,
    filters,
    tenantId = null,
    limit = 500,
    maxPages = 4,
    serviceAreaBounds,
    filterBounds = null,
    refreshIntervalMs = 0,
    refreshKey = 0,
    now,
  } = options;

  const [answer, setAnswer] = useState<Answer | null>(null);
  const [tick, setTick] = useState(0);
  const nowRef = useRef<() => Date>(() => new Date());
  useEffect(() => {
    nowRef.current = now ?? (() => new Date());
  }, [now]);

  const waiting = serviceAreaBounds === undefined;
  const bounds =
    viewWindow === null
      ? null
      : narrow(viewWindow.bounds, serviceAreaBounds ?? null, filterBounds);
  const outside = viewWindow !== null && bounds === null;
  const active = enabled && !outside && !waiting;
  const key = active
    ? JSON.stringify([
        bounds,
        filters.eventType,
        filters.sourceType,
        filters.windowHours,
        filters.from,
        filters.to,
        tenantId,
        limit,
        maxPages,
        refreshKey,
        tick,
      ])
    : '';

  useEffect(() => {
    if (refreshIntervalMs <= 0 || !active) {
      return;
    }
    const timer = setInterval(() => {
      setTick((value) => value + 1);
    }, refreshIntervalMs);
    return () => {
      clearInterval(timer);
    };
  }, [refreshIntervalMs, active]);

  useEffect(() => {
    if (!active) {
      return;
    }
    const controller = new AbortController();
    const requested = eventWindow(filters, nowRef.current());

    const load = async (): Promise<Omit<Answer, 'key' | 'error' | 'loadedAt'>> => {
      const collected: ApiFeature[] = [];
      let cursor: string | null = null;
      let answered: TimeWindow = requested;
      let truncated = false;
      for (let page = 0; page < maxPages; page += 1) {
        const page_ = await api.listEvents(
          {
            from: requested.from,
            to: requested.to,
            bounds,
            eventType: filters.eventType,
            sourceType: filters.sourceType,
            tenantId,
            limit,
            cursor,
          },
          { signal: controller.signal },
        );
        collected.push(...page_.features);
        answered = page_.window;
        cursor = page_.nextCursor ?? null;
        if (cursor === null) {
          break;
        }
        truncated = page === maxPages - 1;
      }
      return { features: collected, window: answered, truncated };
    };

    load().then(
      (loaded) => {
        if (!controller.signal.aborted) {
          setAnswer({ key, ...loaded, error: null, loadedAt: nowRef.current() });
        }
      },
      (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setAnswer({
          key,
          features: NO_FEATURES,
          window: requested,
          truncated: false,
          error: error instanceof Error ? error : new Error(String(error)),
          loadedAt: nowRef.current(),
        });
      },
    );
    return () => {
      controller.abort();
    };
    // `key` is the identity of the request; the values it is built from are read inside.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key, active]);

  return useMemo(() => {
    if (!enabled) {
      return { ...IDLE, reason: 'hidden' as const };
    }
    if (outside) {
      return { ...IDLE, reason: 'outside' as const };
    }
    if (waiting) {
      return { ...IDLE, reason: 'waiting' as const };
    }
    if (answer === null) {
      return { ...IDLE, status: 'loading' as const };
    }
    if (answer.key !== key) {
      return {
        status: 'loading' as const,
        features: answer.features,
        error: null,
        window: answer.window,
        truncated: answer.truncated,
        reason: null,
        loadedAt: answer.loadedAt,
      };
    }
    return {
      status: answer.error === null ? ('success' as const) : ('error' as const),
      features: answer.features,
      error: answer.error,
      window: answer.window,
      truncated: answer.truncated,
      reason: null,
      loadedAt: answer.loadedAt,
    };
  }, [answer, enabled, key, outside, waiting]);
}
