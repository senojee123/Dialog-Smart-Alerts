/**
 * The map client.
 *
 * `MapContainer` is the component a larger application embeds: it owns the map, the layers, the
 * selection, the tools and the editor, and it takes everything it needs as props - an API client, a
 * tenant, which panels to show, and how to find out what state a device is in. It keeps no global state
 * and registers nothing on `window`, so more than one can be mounted, and a host can drive it from its
 * own UI by passing `panels={[]}` and using the exported hooks.
 *
 * What it shows is geography: where things are, what is near what, what an area contains, what was
 * observed where. Deciding what follows from any of that is not this component's business, and not this
 * service's (ADR-0012).
 *
 * What it offers follows the caller's permissions (`GET /geo/v1/me`, see `access.ts`): the editor, the
 * event layer, the spatial questions and exports appear only for a caller the service would let use them.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { GeoJSONSource, Map as MapLibreMap } from 'maplibre-gl';
import {
  AttributionControl,
  Layer,
  Map as MapView,
  NavigationControl,
  ScaleControl,
  Source,
  type MapLayerMouseEvent,
} from 'react-map-gl/maplibre';

import { config, NEUTRAL_BASEMAP, type Basemap } from '../config';
import { ApiError } from '../services/apiClient';
import { abilitiesOf } from './access';
import { boundsFromBbox, type Bounds } from '../geo/geometry';
import type { Position } from '../geo/sld99';
import { useApiResource } from '../hooks/useApiResource';
import { gisApi, type GisApi } from '../services/gisApi';
import type { ApiFeature, Geofence, Geometry } from '../types/api';
import { MapControls } from './controls/MapControls';
import { EventFilters } from './controls/EventFilters';
import { ExportPanel } from './controls/ExportPanel';
import { Legend } from './controls/Legend';
import { MapStatus } from './controls/MapStatus';
import {
  GeofenceEditor,
  type GeofenceDrawHandlers,
} from './editor/GeofenceEditor';
import { draftShape as shapeOfDraft, type GeofenceDraft } from './editor/geofenceDraft';
import { useTerraDraw, type DrawnShape, type TerraDrawController } from './editor/useTerraDraw';
import { EVENT_CLUSTER_LAYER, EVENT_POINT_SOURCE } from './layers/EventLayer';
import { EVENT_LAYER_ID, MAP_LAYERS, type MapLayerDefinition } from './layers/layerCatalogue';
import { LayerManager, type LayerReport } from './layers/LayerManager';
import { OverlayLayer } from './layers/OverlayLayer';
import { ALL_PANELS, interactiveIdsFor, type PanelId } from './panels';
import {
  INITIAL_VIEW,
  resolveMapStyle,
  SERVICE_AREA_SOURCE_ID,
  serviceAreaBounds,
  type MapView as CameraView,
} from './mapStyle';
import { configureMapLibre, supportsWebGL2 } from './maplibreSetup';
import { FeaturePopup } from './popup/FeaturePopup';
import {
  asSourceData,
  geometrySource,
  readGeometry,
  FEATURE_ID_PROPERTY,
  LAYER_ID_PROPERTY,
} from './sourceData';
import {
  defaultEventFilters,
  eventWindow,
  type EventFilterState,
  type Selection,
} from './state/mapState';
import { useBoundsWindow, type Viewport } from './state/useBoundsWindow';
import type { EventLayerData } from './state/useEventLayer';
import { NO_FEATURES } from './state/useFeatureLayer';
import { useLayerVisibility, defaultVisibleLayers } from './state/useLayerVisibility';
import { useReverseGeocode } from './state/useReverseGeocode';
import { SpatialTools } from './tools/SpatialTools';
import { cumulativeLabels, TOOL_HINTS } from './tools/spatialToolModel';
import { useSpatialTools } from './tools/useSpatialTools';
import type { DeviceStateLookup } from './layers/DeviceLayer';

const maplibre = configureMapLibre();
const FIT_PADDING = 32;

export interface MapContainerProps {
  /** The API client; the default is configured from `VITE_*` (see `config.ts`). */
  readonly api?: GisApi;
  /** Tenant whose operational data to show (default: the configured tenant, else the platform's organisation). */
  readonly tenantId?: string | null;
  readonly basemaps?: readonly Basemap[];
  readonly initialBasemapId?: string;
  readonly initialVisibleLayers?: ReadonlySet<string>;
  /**
   * Where the map starts. Without one it frames the service area once that has loaded; with one (a linked
   * view, `#map=<zoom>/<lat>/<lon>` in the reference application) it stays where it was asked to be.
   */
  readonly initialView?: CameraView | null;
  /** Which side panels to render; `[]` leaves the UI entirely to the host application. */
  readonly panels?: readonly PanelId[];
  /**
   * What state a device is in, from whatever service knows. The GIS service records where a device is,
   * not whether it is working, so a device without a report is drawn as "not reported".
   */
  readonly deviceState?: DeviceStateLookup;
  readonly featureLimit?: number;
  readonly maxFeaturePages?: number;
  readonly eventWindowHours?: number;
  readonly eventRefreshIntervalMs?: number;
  readonly onSelectionChange?: (selection: Selection | null) => void;
  readonly onViewportChange?: (viewport: Viewport) => void;
}

export function MapContainer(props: MapContainerProps) {
  const {
    api = gisApi,
    tenantId = config.tenantId,
    basemaps = config.basemaps,
    initialBasemapId = config.defaultBasemapId,
    initialVisibleLayers,
    initialView = null,
    panels = ALL_PANELS,
    deviceState,
    featureLimit = config.featureLimit,
    maxFeaturePages = config.maxFeaturePages,
    eventWindowHours = config.eventWindowHours,
    eventRefreshIntervalMs = config.eventRefreshIntervalMs,
    onSelectionChange,
    onViewportChange,
  } = props;

  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [viewport, setViewport] = useState<Viewport | null>(null);
  const [basemapId, setBasemapId] = useState(initialBasemapId);
  const [showLabels, setShowLabels] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [reports, setReports] = useState<Readonly<Record<string, LayerReport>>>({});
  const [selection, setSelection] = useState<Selection | null>(null);
  const [contextWanted, setContextWanted] = useState(false);
  const [filterArea, setFilterArea] = useState<Geometry | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Geofence | null>(null);
  const [editorProblem, setEditorProblem] = useState<string | null>(null);
  const [draft, setDraft] = useState<GeofenceDraft | null>(null);
  const [eventData, setEventData] = useState<EventLayerData | null>(null);
  const [styleFailed, setStyleFailed] = useState(false);
  const [eventFilters, setEventFilters] = useState<EventFilterState>(() =>
    defaultEventFilters(eventWindowHours),
  );

  const visibility = useLayerVisibility(initialVisibleLayers ?? defaultVisibleLayers());
  const viewWindow = useBoundsWindow(viewport);

  const loadServiceArea = useCallback(
    (signal: AbortSignal) => api.getServiceArea({ signal }),
    [api],
  );
  const loadCatalogue = useCallback(
    (signal: AbortSignal) => api.getLayerCatalogue({ signal, tenantId }),
    [api, tenantId],
  );
  const loadIdentity = useCallback((signal: AbortSignal) => api.getIdentity({ signal }), [api]);
  const serviceArea = useApiResource(loadServiceArea);
  const catalogue = useApiResource(loadCatalogue);
  const identity = useApiResource(loadIdentity);
  const abilities = useMemo(() => abilitiesOf(identity.data), [identity.data]);

  /**
   * The service area, once it is known: `undefined` while it is still loading, so a layer waits instead
   * of asking for a box wider than the service will accept, and `null` if it could not be read at all.
   */
  const areaBounds: Bounds | null | undefined =
    serviceArea.data !== null
      ? boundsFromBbox(serviceArea.data.properties.bbox)
      : serviceArea.status === 'error'
        ? null
        : undefined;

  const tools = useSpatialTools({ api, tenantId, catalogue: catalogue.data });

  // One Terra Draw instance serves the editor and draw-to-filter; what a drawing is for travels with it.
  const drawRef = useRef<TerraDrawController | null>(null);
  const geofenceHandlers = useRef<GeofenceDrawHandlers | null>(null);

  const handleDrawFinish = useCallback((shape: DrawnShape, purpose: 'geofence' | 'filter') => {
    if (purpose === 'filter') {
      setFilterArea(shape.geometry);
      // Only the filter's own shape: a geofence being edited shares the instance and must stay.
      drawRef.current?.remove(shape.id);
      drawRef.current?.setMode('static', 'filter');
      return;
    }
    geofenceHandlers.current?.onFinish(shape);
  }, []);

  const handleDrawChange = useCallback(
    (id: string, shape: DrawnShape | null, purpose: 'geofence' | 'filter') => {
      if (purpose === 'geofence') {
        geofenceHandlers.current?.onChange(id, shape);
      }
    },
    [],
  );

  const draw = useTerraDraw({
    map,
    enabled: true,
    onFinish: handleDrawFinish,
    onChange: handleDrawChange,
  });
  const { finishedRecently } = draw;
  useEffect(() => {
    drawRef.current = draw;
  }, [draw]);

  const registerDrawHandlers = useCallback((handlers: GeofenceDrawHandlers | null) => {
    geofenceHandlers.current = handlers;
  }, []);

  // Arming the filter tool hands the pointer to Terra Draw; leaving it takes it back.
  const armFilterDrawing = tools.tool === 'filter' && filterArea === null;
  useEffect(() => {
    if (!draw.ready) {
      return;
    }
    if (armFilterDrawing) {
      draw.setMode('polygon', 'filter');
    } else if (draw.purpose === 'filter' && draw.drawing) {
      draw.setMode('static', 'filter');
    }
    // The controller is stable; arming is what changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [armFilterDrawing, draw.ready]);

  const availableLayers = useMemo<readonly MapLayerDefinition[]>(() => {
    const published = catalogue.data?.layers;
    // The event layer only for a caller who may read events: otherwise it could only ever say 403.
    const offered = abilities.readEvents
      ? MAP_LAYERS
      : MAP_LAYERS.filter((layer) => layer.id !== EVENT_LAYER_ID);
    if (published === undefined) {
      return offered;
    }
    const codes = new Set(published.filter((layer) => layer.queryable).map((layer) => layer.code));
    return offered.filter((layer) => layer.apiLayer === null || codes.has(layer.apiLayer));
  }, [catalogue.data, abilities.readEvents]);

  // The service refuses to export reference data whose licence does not allow redistribution.
  const exportableLayers = useMemo<readonly MapLayerDefinition[]>(() => {
    const refused = new Set(
      (catalogue.data?.layers ?? []).filter((layer) => !layer.exportable).map((layer) => layer.code),
    );
    return availableLayers.filter((layer) => layer.apiLayer === null || !refused.has(layer.apiLayer));
  }, [availableLayers, catalogue.data]);

  const readViewport = useCallback(
    (instance: MapLibreMap) => {
      const bounds = instance.getBounds();
      const next: Viewport = {
        bounds: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
        zoom: instance.getZoom(),
      };
      setViewport(next);
      onViewportChange?.(next);
    },
    [onViewportChange],
  );

  const handleLoad = useCallback(
    (instance: MapLibreMap) => {
      setMap(instance);
      readViewport(instance);
    },
    [readViewport],
  );

  // The first service area to arrive frames the map, unless the host asked for a view; later ones do not
  // move it under the operator.
  const framed = useRef(initialView !== null);
  useEffect(() => {
    if (map === null || serviceArea.data === null || framed.current) {
      return;
    }
    framed.current = true;
    map.fitBounds(serviceAreaBounds(serviceArea.data), { padding: FIT_PADDING, duration: 0 });
    readViewport(map);
  }, [serviceArea.data, readViewport, map]);

  const handleLayerReport = useCallback((layerId: string, report: LayerReport) => {
    setReports((current) => {
      const previous = current[layerId];
      const unchanged =
        previous?.status === report.status &&
        previous.count === report.count &&
        previous.truncated === report.truncated &&
        previous.refDataRelease === report.refDataRelease &&
        previous.reason === report.reason &&
        previous.error === report.error;
      if (unchanged) {
        return current;
      }
      return { ...current, [layerId]: report };
    });
  }, []);

  const select = useCallback(
    (next: Selection | null) => {
      setSelection(next);
      setContextWanted(next !== null && next.layerId === EVENT_LAYER_ID);
      onSelectionChange?.(next);
    },
    [onSelectionChange],
  );

  const zoomToCluster = useCallback(
    (clusterId: number, position: Position) => {
    const instance = map;
    if (instance === null) {
      return;
    }
    const source = instance.getSource(EVENT_POINT_SOURCE);
    if (source?.type !== 'geojson') {
      return;
    }
    (source as GeoJSONSource).getClusterExpansionZoom(clusterId).then(
      (zoom) => {
        instance.easeTo({ center: { lng: position[0], lat: position[1] }, zoom, duration: 400 });
      },
      () => {
        instance.easeTo({ center: { lng: position[0], lat: position[1] }, zoom: instance.getZoom() + 2 });
      },
    );
    },
    [map],
  );

  const handleClick = useCallback(
    (event: MapLayerMouseEvent) => {
      const position: Position = [event.lngLat.lng, event.lngLat.lat];
      if (draw.drawing || finishedRecently()) {
        return;
      }
      if (tools.tool === 'measure' || tools.tool === 'radius' || tools.tool === 'nearby') {
        tools.handleClick(position);
        return;
      }
      const features = event.features ?? [];
      const cluster = features.find((feature) => feature.layer.id === EVENT_CLUSTER_LAYER);
      if (cluster !== undefined) {
        const clusterId: unknown = cluster.properties.cluster_id;
        if (typeof clusterId === 'number') {
          zoomToCluster(clusterId, position);
        }
        return;
      }
      const picked = features[0];
      if (picked === undefined) {
        select(null);
        return;
      }
      const properties = picked.properties as Record<string, unknown>;
      const featureId = properties[FEATURE_ID_PROPERTY];
      const layerId = properties[LAYER_ID_PROPERTY];
      if (typeof featureId !== 'string' || typeof layerId !== 'string') {
        select(null);
        return;
      }
      select({
        layerId,
        featureId,
        properties,
        geometry: readGeometry(picked.geometry),
        position,
      });
    },
    [draw.drawing, finishedRecently, tools, select, zoomToCluster],
  );

  const context = useReverseGeocode(api, selection?.position ?? null, contextWanted);

  // Which request for a geofence to edit is the one still wanted: closing the editor, starting a new
  // geofence or opening another one makes an answer still on its way stale, and a stale answer must not
  // put a geofence into an editor the operator is using for something else (saving would replace it).
  const editorRequest = useRef(0);

  const openGeofence = useCallback(
    (geofenceId: string) => {
      editorRequest.current += 1;
      const request = editorRequest.current;
      setEditorOpen(true);
      setEditorProblem(null);
      api.getGeofence(geofenceId, { tenantId }).then(
        (geofence) => {
          if (request === editorRequest.current) {
            setEditing(geofence);
          }
        },
        (error: unknown) => {
          if (request !== editorRequest.current) {
            return;
          }
          // A geofence of another tenant, or one shared for reading only, cannot be opened: say so
          // rather than presenting an empty editor that would create a duplicate.
          setEditing(null);
          setEditorProblem(
            error instanceof ApiError
              ? `That geofence could not be opened: ${error.summary}`
              : `That geofence could not be opened: ${error instanceof Error ? error.message : String(error)}`,
          );
        },
      );
    },
    [api, tenantId],
  );

  const interactiveLayerIds = useMemo(
    () => interactiveIdsFor(visibility.visible, availableLayers, showLabels),
    [visibility.visible, availableLayers, showLabels],
  );

  /**
   * What the panels show about the layers: only the ones that are on. A layer reports its state while it
   * is mounted, so turning off a layer that failed has to take its message off the map with it.
   */
  const activeReports = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(reports).filter(([layerId]) => visibility.visible.has(layerId)),
      ),
    [reports, visibility.visible],
  );

  const basemap = basemaps.find((candidate) => candidate.id === basemapId) ?? NEUTRAL_BASEMAP;

  const styleUrl = styleFailed ? null : basemap.styleUrl;
  const eventReport = reports[EVENT_LAYER_ID];


  const eventsLoaded = eventData?.features ?? NO_FEATURES;
  // The type filter offers every type seen since the map opened (per tenant), not only those in the last
  // load: that load is already filtered by type, so choosing one would otherwise leave nothing else to
  // choose. Kept in state and extended during render, which React allows for a guarded update.
  const [seenEventTypes, setSeenEventTypes] = useState<SeenEventTypes>(() => ({ tenantId, types: [] }));
  const loadedEventTypes = useMemo(() => distinct(eventsLoaded, 'eventType'), [eventsLoaded]);
  const rememberedEventTypes = seenEventTypes.tenantId === tenantId ? seenEventTypes.types : NO_TYPES;
  const knownEventTypes = useMemo(
    () => mergeSorted(rememberedEventTypes, loadedEventTypes),
    [rememberedEventTypes, loadedEventTypes],
  );
  if (seenEventTypes.tenantId !== tenantId || knownEventTypes.length !== seenEventTypes.types.length) {
    setSeenEventTypes({ tenantId, types: knownEventTypes });
  }
  const knownSourceTypes = useMemo(() => distinct(eventsLoaded, 'sourceType'), [eventsLoaded]);

  // What an event export selects: the filters in force and the view, with a relative window resolved when
  // the operator asks for the file.
  const viewBounds = viewport?.bounds ?? null;
  const eventSelection = useCallback(
    () => ({
      ...eventWindow(eventFilters, new Date()),
      bounds: viewBounds,
      eventType: eventFilters.eventType,
      sourceType: eventFilters.sourceType,
      tenantId,
    }),
    [eventFilters, viewBounds, tenantId],
  );

  // Checked once per mount: creating a probe canvas on every render would be wasteful.
  const webgl2 = useMemo(() => supportsWebGL2(), []);

  const focus = useCallback(
    (position: readonly [number, number]) => {
      map?.easeTo({ center: { lng: position[0], lat: position[1] }, zoom: 14, duration: 400 });
    },
    [map],
  );

  if (!webgl2) {
    return (
      <p className="notice notice--error map-client__no-webgl">
        This browser does not support WebGL2, which the map requires. Use a current version of Chrome,
        Edge, Firefox or Safari with hardware acceleration enabled.
      </p>
    );
  }

  const showPanel = (panel: PanelId): boolean => panels.includes(panel);
  const editorOffered = showPanel('editor') && abilities.editGeofences;

  return (
    <div className="map-client">
      <div className="map-client__map" role="region" aria-label="Map">
        <MapView
          mapLib={maplibre}
          initialViewState={initialView ?? INITIAL_VIEW}
          mapStyle={resolveMapStyle(styleUrl)}
          attributionControl={false}
          interactiveLayerIds={[...interactiveLayerIds]}
          onLoad={(event) => {
            handleLoad(event.target);
          }}
          onMoveEnd={(event) => {
            readViewport(event.target);
          }}
          onClick={handleClick}
          onError={(event) => {
            // A style that cannot be fetched fails either with its URL in the message (an HTTP error) or
            // with none at all (CORS, DNS, offline). Either way, if the style has not loaded, it is the
            // style that failed, and the neutral background is what the operator gets.
            const named = basemap.styleUrl !== null && event.error.message.includes(basemap.styleUrl);
            const styleMissing = map !== null && !map.isStyleLoaded();
            if (basemap.styleUrl !== null && (named || styleMissing)) {
              setStyleFailed(true);
            }
          }}
          cursor={tools.tool === null ? 'grab' : 'crosshair'}
          style={{ width: '100%', height: '100%' }}
        >
          <NavigationControl position="top-right" visualizePitch={false} />
          <ScaleControl position="bottom-left" unit="metric" maxWidth={160} />
          {/* Reference data licences (ODbL, CC BY) require their attribution wherever the data is shown.
              The control reads its options once, so it is recreated when the attribution changes. */}
          <AttributionControl
            key={catalogue.data?.attribution.join('\n') ?? ''}
            position="bottom-right"
            compact
            {...(catalogue.data?.attribution.length ? { customAttribution: catalogue.data.attribution } : {})}
          />

          {serviceArea.data !== null && (
            <Source
              id={SERVICE_AREA_SOURCE_ID}
              type="geojson"
              data={asSourceData(geometrySource(serviceArea.data.geometry))}
            >
              <Layer
                id="service-area-outline"
                type="line"
                paint={{ 'line-color': '#2e6db4', 'line-width': 1.5, 'line-dasharray': [3, 2] }}
              />
            </Source>
          )}

          <LayerManager
            api={api}
            window={viewWindow}
            visible={visibility.visible}
            availableLayers={availableLayers}
            tenantId={tenantId}
            serviceAreaBounds={areaBounds}
            eventFilters={eventFilters}
            filterArea={filterArea}
            selectedFeatureId={selection?.featureId ?? null}
            selectedLayerId={selection?.layerId ?? null}
            showLabels={showLabels}
            {...(deviceState === undefined ? {} : { deviceState })}
            featureLimit={featureLimit}
            maxFeaturePages={maxFeaturePages}
            eventRefreshIntervalMs={eventRefreshIntervalMs}
            refreshKey={refreshKey}
            onLayerReport={handleLayerReport}
            onEventData={setEventData}
          />

          <OverlayLayer
            measure={tools.measure}
            measureLabels={cumulativeLabels(tools.measure)}
            searchCircle={tools.circle}
            filterArea={filterArea}
            results={tools.results}
            draft={draft === null ? null : shapeOfDraft(draft)}
          />

          {selection !== null && (
            <FeaturePopup
              selection={selection}
              context={context}
              onClose={() => {
                select(null);
              }}
              onRequestContext={() => {
                setContextWanted(true);
              }}
              {...(editorOffered ? { onEditGeofence: openGeofence } : {})}
              {...(deviceState === undefined ? {} : { deviceState })}
            />
          )}
        </MapView>

        <MapStatus
          reports={activeReports}
          mapReady={map !== null}
          styleFailed={styleFailed}
          basemapConfigured={basemaps.some((candidate) => candidate.styleUrl !== null)}
          interaction={tools.tool === null ? null : TOOL_HINTS[tools.tool]}
        />

        {showPanel('legend') && (
          <div className="map-client__legend">
            <Legend visible={visibility.visible} availableLayers={availableLayers} />
          </div>
        )}
      </div>

      {panels.length > 0 && (
        <aside className="map-client__panels">
          {showPanel('layers') && (
            <MapControls
              visibility={visibility}
              availableLayers={availableLayers}
              reports={activeReports}
              basemaps={basemaps}
              basemapId={basemapId}
              onBasemapChange={(id) => {
                // Another basemap deserves its own chance: a failure applies to the style that failed.
                setStyleFailed(false);
                setBasemapId(id);
              }}
              showLabels={showLabels}
              onShowLabelsChange={setShowLabels}
              onRefresh={() => {
                setRefreshKey((value) => value + 1);
              }}
            />
          )}

          {showPanel('events') && abilities.readEvents && (
            <EventFilters
              filters={eventFilters}
              onChange={setEventFilters}
              knownEventTypes={knownEventTypes}
              knownSourceTypes={knownSourceTypes}
              answeredWindow={eventData?.window ?? null}
              count={eventReport?.count ?? 0}
              truncated={eventReport?.truncated ?? false}
              loadedAt={eventData?.loadedAt ?? null}
              onRefresh={() => {
                setRefreshKey((value) => value + 1);
              }}
              disabled={!visibility.isVisible(EVENT_LAYER_ID)}
            />
          )}

          {showPanel('tools') && (
            <SpatialTools
              tools={tools}
              catalogue={catalogue.data}
              filterActive={filterArea !== null}
              onClearFilter={() => {
                setFilterArea(null);
                drawRef.current?.clear();
              }}
              onFocus={focus}
              queryTools={abilities.askSpatialQuestions}
            />
          )}

          {showPanel('export') && abilities.exportData && (
            <ExportPanel
              api={api}
              tenantId={tenantId}
              layers={exportableLayers}
              bounds={viewBounds}
              events={abilities.readEvents ? eventSelection : null}
            />
          )}

          {editorOffered &&
            (editorOpen ? (
              <>
                {editorProblem !== null && (
                  <p className="notice notice--error panel" role="alert">
                    {editorProblem}
                  </p>
                )}
                <GeofenceEditor
                  key={editing?.id ?? 'new'}
                  api={api}
                  draw={draw}
                  registerDrawHandlers={registerDrawHandlers}
                  tenantId={tenantId}
                  serviceAreaBounds={areaBounds ?? null}
                  initialGeofence={editing}
                  onDraftChange={setDraft}
                  onSaved={() => {
                    setRefreshKey((value) => value + 1);
                  }}
                  onClose={() => {
                    editorRequest.current += 1;
                    setEditorOpen(false);
                    setEditing(null);
                    setEditorProblem(null);
                    setDraft(null);
                    drawRef.current?.clear();
                    drawRef.current?.setMode('static', 'geofence');
                  }}
                />
              </>
            ) : (
              <section className="panel">
                <header className="panel__header">
                  <h2>Geofences</h2>
                  <button
                    type="button"
                    className="button button--primary"
                    onClick={() => {
                      editorRequest.current += 1;
                      setEditing(null);
                      setEditorOpen(true);
                    }}
                  >
                    New geofence
                  </button>
                </header>
                <p className="muted">
                  Draw a polygon, a circle or a corridor, or select a geofence on the map to edit it.
                </p>
              </section>
            ))}
        </aside>
      )}
    </div>
  );
}

interface SeenEventTypes {
  readonly tenantId: string | null | undefined;
  readonly types: readonly string[];
}

const NO_TYPES: readonly string[] = [];

function mergeSorted(a: readonly string[], b: readonly string[]): readonly string[] {
  if (b.every((value) => a.includes(value))) {
    return a;
  }
  return [...new Set([...a, ...b])].sort((x, y) => x.localeCompare(y));
}

function distinct(features: readonly ApiFeature[], property: string): readonly string[] {
  const values = new Set<string>();
  for (const feature of features) {
    const value = feature.properties[property];
    if (typeof value === 'string' && value !== '') {
      values.add(value);
    }
  }
  return [...values].sort((a, b) => a.localeCompare(b));
}
