/**
 * Where a position is: the administrative hierarchy and the nearest named places.
 *
 * This is the geographic context the service computes (`GET /geo/v1/reverse`). An event carries the
 * administrative *codes* its geo-context recorded; resolving them to names, and finding the nearest
 * settlement and road, is this request.
 */
import { useEffect, useMemo, useState } from 'react';

import { ApiError } from '../../services/apiClient';
import type { GisApi } from '../../services/gisApi';
import type { Position } from '../../geo/sld99';
import type { ReverseGeocode } from '../../types/api';

export interface ReverseGeocodeState {
  readonly status: 'idle' | 'loading' | 'success' | 'error';
  readonly data: ReverseGeocode | null;
  readonly error: string | null;
}

const IDLE: ReverseGeocodeState = { status: 'idle', data: null, error: null };
const LOADING: ReverseGeocodeState = { status: 'loading', data: null, error: null };

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return error.summary;
  }
  return error instanceof Error ? error.message : String(error);
}

export function useReverseGeocode(
  api: GisApi,
  position: Position | null,
  enabled: boolean,
): ReverseGeocodeState {
  const key = position === null || !enabled ? '' : `${position[0]},${position[1]}`;
  const [answer, setAnswer] = useState<
    { readonly key: string; readonly data: ReverseGeocode | null; readonly error: string | null } | null
  >(null);

  useEffect(() => {
    if (key === '' || position === null) {
      return;
    }
    const controller = new AbortController();
    api.reverseGeocode(position, { signal: controller.signal }).then(
      (data) => {
        if (!controller.signal.aborted) {
          setAnswer({ key, data, error: null });
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setAnswer({ key, data: null, error: describe(error) });
        }
      },
    );
    return () => {
      controller.abort();
    };
    // The position is the request, and `key` is its identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, key]);

  return useMemo(() => {
    if (key === '') {
      return IDLE;
    }
    if (answer?.key !== key) {
      return LOADING;
    }
    return answer.error !== null
      ? { status: 'error' as const, data: null, error: answer.error }
      : { status: 'success' as const, data: answer.data, error: null };
  }, [answer, key]);
}
