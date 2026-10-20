/**
 * The state of the spatial tools: which one is armed, what it was given, and what it answered.
 *
 * The map routes a click to `handleClick` while a tool is armed; radius and nearby searches then run
 * against the API, the ruler adds a position, and drawing a filter area is handed to Terra Draw by the
 * container. Results are features, which the overlay draws and the panel lists.
 */
import { useCallback, useMemo, useRef, useState } from 'react';

import type { Position } from '../../geo/sld99';
import { ApiError } from '../../services/apiClient';
import type { GisApi } from '../../services/gisApi';
import type { ApiFeature, LayerCatalogue } from '../../types/api';
import {
  DEFAULT_NEAREST_LIMIT,
  DEFAULT_NEAREST_MAX_DISTANCE_M,
  DEFAULT_RADIUS_M,
  DEVICE_LAYER_CODE,
  defaultTarget,
  resultRows,
  type ResultRow,
  type ToolId,
} from './spatialToolModel';

export type ToolStatus = 'idle' | 'running' | 'done' | 'error';

export interface SpatialToolsOptions {
  readonly api: GisApi;
  readonly tenantId: string | null;
  readonly catalogue: LayerCatalogue | null;
}

export interface SpatialTools {
  readonly tool: ToolId | null;
  readonly target: string;
  /** The answer no longer matches what is set: the distance or the layer changed since it was run. */
  readonly stale: boolean;
  readonly radiusM: number;
  readonly nearestLimit: number;
  readonly centre: Position | null;
  readonly measure: readonly Position[];
  readonly results: readonly ApiFeature[];
  readonly rows: readonly ResultRow[];
  readonly status: ToolStatus;
  readonly error: string | null;
  readonly truncated: boolean;
  readonly circle: { readonly centre: Position; readonly radiusM: number } | null;
  selectTool: (tool: ToolId | null) => void;
  setTarget: (target: string) => void;
  setRadiusM: (radiusM: number) => void;
  setNearestLimit: (limit: number) => void;
  handleClick: (position: Position) => void;
  undoMeasure: () => void;
  clearResults: () => void;
  rerun: () => void;
}

export function useSpatialTools(options: SpatialToolsOptions): SpatialTools {
  const { api, tenantId, catalogue } = options;
  const [tool, setTool] = useState<ToolId | null>(null);
  // The target is chosen by the operator or, until then, by the service's catalogue - which arrives after
  // the first render, so it cannot be an initial value.
  const [chosenTarget, setChosenTarget] = useState<string | null>(null);
  const target = chosenTarget ?? defaultTarget(catalogue);
  const [radiusM, setRadiusM] = useState(DEFAULT_RADIUS_M);
  const [nearestLimit, setNearestLimit] = useState(DEFAULT_NEAREST_LIMIT);
  const [centre, setCentre] = useState<Position | null>(null);
  const [measure, setMeasure] = useState<readonly Position[]>([]);
  const [results, setResults] = useState<readonly ApiFeature[]>([]);
  const [status, setStatus] = useState<ToolStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  /** What the answer on screen was computed from, so a change to the settings can be reported. */
  const [answered, setAnswered] = useState<{ target: string; radiusM: number; limit: number } | null>(
    null,
  );
  const running = useRef<AbortController | null>(null);

  const run = useCallback(
    (which: 'radius' | 'nearby', position: Position, settings: { target: string; radiusM: number; limit: number }) => {
      running.current?.abort();
      const controller = new AbortController();
      running.current = controller;
      setStatus('running');
      setError(null);
      setTruncated(false);
      setAnswered({ target: settings.target, radiusM: settings.radiusM, limit: settings.limit });

      const request =
        which === 'radius'
          ? api.queryWithinDistance(
              {
                target: settings.target,
                geometry: { type: 'Point', coordinates: position },
                distanceM: settings.radiusM,
                tenantId,
                limit: 200,
              },
              { signal: controller.signal },
            )
          : api.queryNearest(
              {
                target: DEVICE_LAYER_CODE,
                geometry: { type: 'Point', coordinates: position },
                maxDistanceM: DEFAULT_NEAREST_MAX_DISTANCE_M,
                limit: settings.limit,
                tenantId,
              },
              { signal: controller.signal },
            );

      request.then(
        (collection) => {
          if (controller.signal.aborted) {
            return;
          }
          setResults(collection.features);
          setTruncated((collection.nextCursor ?? null) !== null);
          setStatus('done');
        },
        (cause: unknown) => {
          if (controller.signal.aborted) {
            return;
          }
          setResults([]);
          setStatus('error');
          setError(
            cause instanceof ApiError
              ? `${cause.summary}${cause.code === null ? '' : ` (${cause.code})`}`
              : cause instanceof Error
                ? cause.message
                : String(cause),
          );
        },
      );
    },
    [api, tenantId],
  );

  const handleClick = useCallback(
    (position: Position) => {
      if (tool === 'measure') {
        setMeasure((current) => [...current, position]);
        return;
      }
      if (tool === 'radius') {
        setCentre(position);
        run('radius', position, { target, radiusM, limit: nearestLimit });
        return;
      }
      if (tool === 'nearby') {
        setCentre(position);
        run('nearby', position, { target, radiusM, limit: nearestLimit });
      }
    },
    [tool, run, target, radiusM, nearestLimit],
  );

  const selectTool = useCallback((next: ToolId | null) => {
    setTool(next);
    setError(null);
    if (next === null || next !== 'measure') {
      setMeasure([]);
    }
    if (next !== 'radius' && next !== 'nearby') {
      setResults([]);
      setCentre(null);
      setStatus('idle');
      setAnswered(null);
    }
  }, []);

  const undoMeasure = useCallback(() => {
    setMeasure((current) => current.slice(0, -1));
  }, []);

  const clearResults = useCallback(() => {
    running.current?.abort();
    setResults([]);
    setCentre(null);
    setMeasure([]);
    setStatus('idle');
    setError(null);
    setTruncated(false);
    setAnswered(null);
  }, []);

  const rerun = useCallback(() => {
    if (centre === null || (tool !== 'radius' && tool !== 'nearby')) {
      return;
    }
    run(tool, centre, { target, radiusM, limit: nearestLimit });
  }, [centre, tool, run, target, radiusM, nearestLimit]);

  const rows = useMemo(
    () => resultRows({ type: 'FeatureCollection', features: [...results], count: results.length }),
    [results],
  );

  const stale =
    answered !== null &&
    status !== 'running' &&
    (tool === 'radius'
      ? answered.target !== target || answered.radiusM !== radiusM
      : tool === 'nearby'
        ? answered.limit !== nearestLimit
        : false);

  return {
    tool,
    target,
    stale,
    radiusM,
    nearestLimit,
    centre,
    measure,
    results,
    rows,
    status,
    error,
    truncated,
    circle: tool === 'radius' && centre !== null ? { centre, radiusM } : null,
    selectTool,
    setTarget: setChosenTarget,
    setRadiusM,
    setNearestLimit,
    handleClick,
    undoMeasure,
    clearResults,
    rerun,
  };
}
