/**
 * Terra Draw, bound to the MapLibre map.
 *
 * Terra Draw owns the pointer while the operator is drawing: it takes the map's drag and double-click
 * handling, keeps its own store of what is being drawn, and renders it on its own layers. This hook owns
 * the instance's lifetime, translates the modes the client offers into Terra Draw's, and hands finished
 * and edited shapes back as plain GeoJSON.
 *
 * There is one instance per map, because two would fight over the pointer. What a drawing is *for* - a
 * geofence, or an area to filter by - travels with it as its `purpose`, so one instance serves both the
 * editor and the spatial tools without either knowing about the other.
 *
 * `static` is Terra Draw's own do-nothing mode, which is what the instance sits in when nothing is being
 * drawn: the map's clicks then go back to selecting features.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Map as MapLibreMap } from 'maplibre-gl';
import {
  TerraDraw,
  TerraDrawCircleMode,
  TerraDrawLineStringMode,
  TerraDrawPolygonMode,
  TerraDrawSelectMode,
  type GeoJSONStoreFeatures,
} from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';

import type { Geometry } from '../../types/api';
import { PALETTE } from '../palette';
import type { DraftKind } from './geofenceDraft';

/** The modes the client offers, and the Terra Draw mode each one uses. */
export type DrawMode = DraftKind | 'select' | 'static';

/** What the current drawing is for. */
export type DrawPurpose = 'geofence' | 'filter';

const TERRA_MODE: Readonly<Record<DrawMode, string>> = {
  polygon: 'polygon',
  circle: 'circle',
  corridor: 'linestring',
  select: 'select',
  static: 'static',
};

export interface DrawnShape {
  readonly id: string;
  readonly geometry: Geometry;
  readonly properties: Readonly<Record<string, unknown>>;
}

export interface TerraDrawOptions {
  /** The MapLibre map to draw on; `null` until it has loaded. */
  readonly map: MapLibreMap | null;
  readonly enabled: boolean;
  /** A shape was completed (a closed polygon, a released circle, a finished line). */
  readonly onFinish: (shape: DrawnShape, purpose: DrawPurpose) => void;
  /**
   * A feature Terra Draw holds changed: a vertex was dragged, or it was deleted (`null`). Terra Draw also
   * reports its own guidance features this way (the handles of a selected shape, the shape being drawn
   * before it is finished), so the receiver must check that `id` is the shape it holds.
   */
  readonly onChange?: (id: string, shape: DrawnShape | null, purpose: DrawPurpose) => void;
}

export interface TerraDrawController {
  readonly ready: boolean;
  readonly mode: DrawMode;
  readonly purpose: DrawPurpose;
  readonly drawing: boolean;
  setMode: (mode: DrawMode, purpose?: DrawPurpose) => void;
  /** Remove everything Terra Draw is holding. */
  clear: () => void;
  /** Put a shape into Terra Draw so it can be edited; returns its id, or `null` if it was refused. */
  load: (geometry: Geometry) => string | null;
  remove: (id: string) => void;
  /**
   * Whether a shape was finished a moment ago. The click that finishes a shape reaches the map as a click
   * too - after the mode has already gone back to static - and must not select what lies under it.
   */
  finishedRecently: () => boolean;
}

/** How long after a shape is finished a map click is still taken to be the finishing click. */
const FINISHING_CLICK_MS = 400;

const DRAW_COLOUR = PALETTE.draft;

/**
 * One of the sources the MapLibre adapter adds (its default prefix is `td`). Replacing the map's style
 * removes it, and the adapter does not add it back, so its absence says the instance must be re-created.
 */
const ADAPTER_SOURCE = 'td-polygon';

function buildModes() {
  const area = { fillColor: DRAW_COLOUR, outlineColor: DRAW_COLOUR, fillOpacity: 0.2 } as const;
  return [
    new TerraDrawPolygonMode({ editable: true, showCoordinatePoints: true, styles: { ...area } }),
    // A circle is drawn in Web Mercator, the projection the map renders in; what the API stores is the
    // centre and the radius, which `definitionFromDrawn` measures back out of the ring.
    new TerraDrawCircleMode({ projection: 'web-mercator', styles: { ...area } }),
    new TerraDrawLineStringMode({
      editable: true,
      styles: { lineStringColor: DRAW_COLOUR, lineStringWidth: 3 },
    }),
    new TerraDrawSelectMode({
      flags: {
        polygon: {
          feature: {
            draggable: true,
            coordinates: { midpoints: true, draggable: true, deletable: true },
          },
        },
        linestring: {
          feature: {
            draggable: true,
            coordinates: { midpoints: true, draggable: true, deletable: true },
          },
        },
        circle: { feature: { draggable: true } },
      },
    }),
  ];
}

function toShape(feature: GeoJSONStoreFeatures): DrawnShape | null {
  const id = feature.id;
  if (id === undefined) {
    return null;
  }
  return {
    id: String(id),
    geometry: feature.geometry as unknown as Geometry,
    properties: feature.properties,
  };
}

export function useTerraDraw(options: TerraDrawOptions): TerraDrawController {
  const { map, enabled, onFinish, onChange } = options;
  const drawRef = useRef<TerraDraw | null>(null);
  const purposeRef = useRef<DrawPurpose>('geofence');
  const [ready, setReady] = useState(false);
  const [mode, setModeState] = useState<DrawMode>('static');
  const [purpose, setPurposeState] = useState<DrawPurpose>('geofence');
  const finishedAtRef = useRef(Number.NEGATIVE_INFINITY);
  const finishRef = useRef(onFinish);
  const changeRef = useRef(onChange);
  useEffect(() => {
    finishRef.current = onFinish;
    changeRef.current = onChange;
  }, [onFinish, onChange]);

  // Switching the basemap (or falling back to the neutral one) replaces the map's style, which takes
  // Terra Draw's sources and layers with it; drawing would then fail on the next render. Each replacement
  // starts a new instance on the new style. What was being drawn is lost, and the editor loads its draft
  // into the new instance again.
  const [styleGeneration, setStyleGeneration] = useState(0);
  useEffect(() => {
    if (map === null || !enabled) {
      return;
    }
    const handleStyleData = () => {
      if (map.getSource(ADAPTER_SOURCE) === undefined) {
        setStyleGeneration((generation) => generation + 1);
      }
    };
    map.on('styledata', handleStyleData);
    return () => {
      map.off('styledata', handleStyleData);
    };
  }, [map, enabled]);

  useEffect(() => {
    if (map === null || !enabled) {
      return;
    }
    let draw: TerraDraw;
    try {
      draw = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map, coordinatePrecision: 9 }),
        modes: buildModes(),
      });
      draw.start();
    } catch {
      // A replacement style that has not finished loading refuses new sources; the next `styledata`
      // event, once it has, tries again.
      return;
    }

    const handleFinish = (id: string | number) => {
      finishedAtRef.current = performance.now();
      const feature = draw.getSnapshotFeature(id);
      const shape = feature === undefined ? null : toShape(feature);
      if (shape !== null) {
        finishRef.current(shape, purposeRef.current);
      }
    };

    const handleChange = (ids: readonly (string | number)[], type: string) => {
      // `create` arrives as `finish` when the shape is complete; this is editing and deleting.
      if (type !== 'update' && type !== 'delete') {
        return;
      }
      for (const id of ids) {
        const feature = type === 'delete' ? undefined : draw.getSnapshotFeature(id);
        changeRef.current?.(
          String(id),
          feature === undefined ? null : toShape(feature),
          purposeRef.current,
        );
      }
    };

    draw.on('finish', handleFinish);
    draw.on('change', handleChange);
    draw.setMode('static');
    drawRef.current = draw;
    // Terra Draw is an external system created here, and whether it exists is what the editor waits
    // for; there is nothing to derive it from, so this state is set once per instance.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReady(true);
    setModeState('static');

    return () => {
      draw.off('finish', handleFinish);
      draw.off('change', handleChange);
      try {
        draw.stop();
      } catch {
        // The map may already be gone when the view unmounts; there is nothing left to clean up.
      }
      drawRef.current = null;
      setReady(false);
    };
  }, [map, enabled, styleGeneration]);

  const setMode = useCallback((next: DrawMode, nextPurpose: DrawPurpose = 'geofence') => {
    const draw = drawRef.current;
    if (draw === null) {
      return;
    }
    purposeRef.current = nextPurpose;
    draw.setMode(TERRA_MODE[next]);
    setModeState(next);
    setPurposeState(nextPurpose);
  }, []);

  const clear = useCallback(() => {
    drawRef.current?.clear();
  }, []);

  const load = useCallback((geometry: Geometry): string | null => {
    const draw = drawRef.current;
    if (draw === null) {
      return null;
    }
    const drawnAs =
      geometry.type === 'Polygon' ? 'polygon' : geometry.type === 'LineString' ? 'linestring' : null;
    if (drawnAs === null) {
      return null;
    }
    const before = new Set(draw.getSnapshot().map((feature) => String(feature.id)));
    const feature = {
      type: 'Feature',
      geometry,
      properties: { mode: drawnAs },
    } as unknown as GeoJSONStoreFeatures;
    const validation = draw.addFeatures([feature]);
    if (validation.some((result) => !result.valid)) {
      return null;
    }
    const added = draw.getSnapshot().find((feature) => !before.has(String(feature.id)));
    return added === undefined ? null : String(added.id);
  }, []);

  const remove = useCallback((id: string) => {
    drawRef.current?.removeFeatures([id]);
  }, []);

  const finishedRecently = useCallback(
    () => performance.now() - finishedAtRef.current < FINISHING_CLICK_MS,
    [],
  );

  // A stable controller: effects that use it must not re-run because a render made a new object.
  return useMemo(
    () => ({
      ready,
      mode,
      purpose,
      drawing: mode !== 'static' && mode !== 'select',
      setMode,
      clear,
      load,
      remove,
      finishedRecently,
    }),
    [ready, mode, purpose, setMode, clear, load, remove, finishedRecently],
  );
}
