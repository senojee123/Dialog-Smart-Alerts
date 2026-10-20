/**
 * The layer manager: what is on the map, in what order, and what state each layer is in.
 *
 * Each visible layer is mounted as its own component, so it owns its request and its loading state and
 * unmounting it is what stops it being loaded. The manager reports every layer's state upwards, which
 * is what the legend and the status line show.
 */
import { memo, useEffect } from 'react';

import { boundsOf, type Bounds } from '../../geo/geometry';
import type { GisApi, LayerFilters } from '../../services/gisApi';
import type { Geometry } from '../../types/api';
import { featuresInArea } from '../sourceData';
import type { EventFilterState } from '../state/mapState';
import type { BoundsWindow } from '../state/useBoundsWindow';
import { useEventLayer, type EventLayerData } from '../state/useEventLayer';
import { useFeatureLayer, type LayerData } from '../state/useFeatureLayer';
import { DeviceLayer, FieldOfViewLayer, SiteLayer, type DeviceStateLookup } from './DeviceLayer';
import { EventLayer } from './EventLayer';
import { GeofenceLayer } from './GeofenceLayer';
import {
  DEVICE_LAYER_ID,
  EVENT_LAYER_ID,
  FEATURE_LAYERS,
  FIELD_OF_VIEW_LAYER_ID,
  GEOFENCE_LAYER_ID,
  SITE_LAYER_ID,
  type MapLayerDefinition,
} from './layerCatalogue';
import { ReferenceLayer } from './ReferenceLayer';

export interface LayerReport {
  readonly status: LayerData['status'];
  readonly count: number;
  readonly error: Error | null;
  readonly truncated: boolean;
  readonly refDataRelease: string | null;
  readonly reason: LayerData['reason'];
}

export type LayerReportHandler = (layerId: string, report: LayerReport) => void;

export interface LayerManagerProps {
  readonly api: GisApi;
  readonly window: BoundsWindow | null;
  readonly visible: ReadonlySet<string>;
  readonly availableLayers: readonly MapLayerDefinition[];
  readonly tenantId: string | null;
  readonly serviceAreaBounds: Bounds | null | undefined;
  readonly eventFilters: EventFilterState;
  readonly filterArea: Geometry | null;
  readonly selectedFeatureId: string | null;
  readonly selectedLayerId: string | null;
  readonly showLabels: boolean;
  readonly deviceState?: DeviceStateLookup;
  readonly featureLimit: number;
  readonly maxFeaturePages: number;
  readonly eventRefreshIntervalMs: number;
  readonly refreshKey: number;
  readonly onLayerReport: LayerReportHandler;
  /** The event layer's own state, which carries the window the service answered for. */
  readonly onEventData?: (data: EventLayerData) => void;
}

/** Report a layer's state upwards whenever it changes, without re-rendering the manager itself. */
function useReport(layerId: string, data: LayerData, onReport: LayerReportHandler, count: number): void {
  const { status, error, truncated, refDataRelease, reason } = data;
  useEffect(() => {
    onReport(layerId, { status, count, error, truncated, refDataRelease, reason });
  }, [layerId, status, count, error, truncated, refDataRelease, reason, onReport]);
}

interface FeatureLayerHostProps extends Omit<LayerManagerProps, 'availableLayers' | 'visible'> {
  readonly definition: MapLayerDefinition;
  readonly filters?: LayerFilters;
}

function FeatureLayerHost(props: FeatureLayerHostProps) {
  const {
    api,
    definition,
    window,
    tenantId,
    serviceAreaBounds,
    filterArea,
    selectedFeatureId,
    selectedLayerId,
    showLabels,
    deviceState,
    featureLimit,
    maxFeaturePages,
    refreshKey,
    onLayerReport,
    filters,
  } = props;

  // The drawn area narrows the request as well as the drawing: the service answers for the box, and the
  // exact test against the drawn shape is done here.
  const filterBounds = filterArea === null ? null : boundsOf(filterArea);

  const data = useFeatureLayer({
    api,
    layer: definition,
    window,
    enabled: true,
    tenantId,
    limit: featureLimit,
    maxPages: maxFeaturePages,
    serviceAreaBounds,
    filterBounds,
    ...(filters === undefined ? {} : { filters }),
    refreshKey,
  });

  // Draw-to-filter narrows what is drawn; the API answered for the viewport, this is the drawn area.
  const features = featuresInArea(data.features, filterArea);
  useReport(definition.id, data, onLayerReport, features.length);

  const selectedHere = selectedLayerId === definition.id ? selectedFeatureId : null;

  switch (definition.id) {
    case DEVICE_LAYER_ID:
      return (
        <DeviceLayer
          features={features}
          selectedFeatureId={selectedHere}
          showLabels={showLabels}
          {...(deviceState === undefined ? {} : { deviceState })}
        />
      );
    case FIELD_OF_VIEW_LAYER_ID:
      return (
        <FieldOfViewLayer
          features={features}
          selectedDeviceId={selectedLayerId === DEVICE_LAYER_ID ? selectedFeatureId : null}
        />
      );
    case SITE_LAYER_ID:
      return (
        <SiteLayer features={features} selectedFeatureId={selectedHere} showLabels={showLabels} />
      );
    case GEOFENCE_LAYER_ID:
      return (
        <GeofenceLayer
          features={features}
          selectedFeatureId={selectedHere}
          showLabels={showLabels}
        />
      );
    default:
      return (
        <ReferenceLayer
          definition={definition}
          features={features}
          selectedFeatureId={selectedHere}
          showLabels={showLabels}
        />
      );
  }
}

function EventLayerHost(props: Omit<LayerManagerProps, 'availableLayers' | 'visible'>) {
  const {
    api,
    window,
    tenantId,
    serviceAreaBounds,
    eventFilters,
    filterArea,
    selectedFeatureId,
    selectedLayerId,
    featureLimit,
    maxFeaturePages,
    eventRefreshIntervalMs,
    refreshKey,
    onLayerReport,
    onEventData,
  } = props;

  const filterBounds = filterArea === null ? null : boundsOf(filterArea);

  const data = useEventLayer({
    api,
    window,
    enabled: true,
    filters: eventFilters,
    tenantId,
    limit: featureLimit,
    maxPages: maxFeaturePages,
    serviceAreaBounds,
    filterBounds,
    refreshIntervalMs: eventRefreshIntervalMs,
    refreshKey,
  });

  const features = featuresInArea(data.features, filterArea);
  useReport(
    EVENT_LAYER_ID,
    { ...data, refDataRelease: null, reason: data.reason },
    onLayerReport,
    features.length,
  );

  useEffect(() => {
    onEventData?.(data);
  }, [data, onEventData]);

  return (
    <EventLayer
      features={features}
      selectedFeatureId={selectedLayerId === EVENT_LAYER_ID ? selectedFeatureId : null}
    />
  );
}

export const LayerManager = memo(function LayerManager(props: LayerManagerProps) {
  const { availableLayers, visible, ...shared } = props;
  const featureLayers = FEATURE_LAYERS.filter(
    (layer) => visible.has(layer.id) && availableLayers.some((known) => known.id === layer.id),
  );

  return (
    <>
      {featureLayers.map((definition) => (
        <FeatureLayerHost key={definition.id} definition={definition} {...shared} />
      ))}
      {visible.has(EVENT_LAYER_ID) && <EventLayerHost {...shared} />}
    </>
  );
});
