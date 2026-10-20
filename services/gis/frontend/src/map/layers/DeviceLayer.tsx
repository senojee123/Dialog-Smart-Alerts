/**
 * Devices and what they observe.
 *
 * A device is drawn at its position, labelled with its identifier, and coloured by state. The state is
 * *not* the GIS service's: this service records where a device is, not whether it is working. The host
 * application supplies a `deviceState` function - typically backed by a device-management or telemetry
 * service - and a device with no report is drawn as "not reported" rather than as healthy
 * (see `docs/frontend/map-client.md`).
 */
import { Layer, Source } from 'react-map-gl/maplibre';

import type { ApiFeature } from '../../types/api';
import { LABEL_FONT } from '../mapStyle';
import { DEVICE_STATE_COLOURS, FILL_OPACITY, PALETTE, type DeviceState } from '../palette';
import { asSourceData, toSourceData } from '../sourceData';
import { DEVICE_LAYER_ID, FIELD_OF_VIEW_LAYER_ID, SITE_LAYER_ID } from './layerCatalogue';
import { pointRadius, selectedFilter, type ColourValue } from './styles';

export const DEVICE_STATE_PROPERTY = '_deviceState';

export const DEVICE_POINT_LAYER = 'devices-point';
export const DEVICE_LABEL_LAYER = 'devices-label';
export const FIELD_OF_VIEW_FILL_LAYER = 'device-fov-fill';
export const SITE_POINT_LAYER = 'sites-point';

/** What the host application knows about a device that the GIS service does not. */
export type DeviceStateLookup = (deviceId: string) => DeviceState | undefined;

const STATE_COLOUR: ColourValue = [
  'match',
  ['get', DEVICE_STATE_PROPERTY],
  'online',
  DEVICE_STATE_COLOURS.online,
  'degraded',
  DEVICE_STATE_COLOURS.degraded,
  'offline',
  DEVICE_STATE_COLOURS.offline,
  DEVICE_STATE_COLOURS.unknown,
];

export interface DeviceLayerProps {
  readonly features: readonly ApiFeature[];
  readonly selectedFeatureId: string | null;
  readonly showLabels: boolean;
  readonly deviceState?: DeviceStateLookup;
}

export function DeviceLayer({
  features,
  selectedFeatureId,
  showLabels,
  deviceState,
}: DeviceLayerProps) {
  const data = toSourceData(DEVICE_LAYER_ID, features, (feature) => ({
    [DEVICE_STATE_PROPERTY]: deviceState?.(feature.id) ?? 'unknown',
  }));

  return (
    <Source id="devices-source" type="geojson" data={asSourceData(data)}>
      <Layer
        id={DEVICE_POINT_LAYER}
        type="circle"
        paint={{
          'circle-radius': pointRadius(4.5, 8),
          'circle-color': STATE_COLOUR,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.5,
        }}
      />
      {showLabels && (
        <Layer
          id={DEVICE_LABEL_LAYER}
          type="symbol"
          layout={{
            'text-font': LABEL_FONT,
            'text-field': ['coalesce', ['get', 'name'], ''],
            'text-size': 11,
            'text-offset': [0, 1.2],
            'text-anchor': 'top',
          }}
          paint={{ 'text-color': PALETTE.device, 'text-halo-color': '#ffffff', 'text-halo-width': 1.2 }}
        />
      )}
      <Layer
        id="devices-selected"
        type="circle"
        filter={selectedFilter(selectedFeatureId)}
        paint={{
          'circle-radius': pointRadius(9, 13),
          'circle-color': 'rgba(0, 0, 0, 0)',
          'circle-stroke-color': PALETTE.draft,
          'circle-stroke-width': 2.5,
        }}
      />
    </Source>
  );
}

export interface FieldOfViewLayerProps {
  readonly features: readonly ApiFeature[];
  readonly selectedDeviceId: string | null;
}

/** The observed area of each device, as the service recorded or modelled it. */
export function FieldOfViewLayer({ features, selectedDeviceId }: FieldOfViewLayerProps) {
  return (
    <Source
      id="device-fov-source"
      type="geojson"
      data={asSourceData(toSourceData(FIELD_OF_VIEW_LAYER_ID, features))}
    >
      <Layer
        id={FIELD_OF_VIEW_FILL_LAYER}
        type="fill"
        paint={{ 'fill-color': PALETTE.fieldOfView, 'fill-opacity': FILL_OPACITY.faint }}
      />
      <Layer
        id="device-fov-line"
        type="line"
        paint={{ 'line-color': PALETTE.fieldOfView, 'line-width': 1, 'line-opacity': 0.8 }}
      />
      <Layer
        id="device-fov-selected"
        type="line"
        filter={['==', ['get', 'deviceId'], selectedDeviceId ?? '\u0000']}
        paint={{ 'line-color': PALETTE.fieldOfView, 'line-width': 2.5 }}
      />
    </Source>
  );
}

export interface SiteLayerProps {
  readonly features: readonly ApiFeature[];
  readonly selectedFeatureId: string | null;
  readonly showLabels: boolean;
}

/** Installation sites: where devices are mounted. */
export function SiteLayer({ features, selectedFeatureId, showLabels }: SiteLayerProps) {
  return (
    <Source id="sites-source" type="geojson" data={asSourceData(toSourceData(SITE_LAYER_ID, features))}>
      <Layer
        id={SITE_POINT_LAYER}
        type="circle"
        paint={{
          'circle-radius': pointRadius(3.5, 6),
          'circle-color': PALETTE.site,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.2,
        }}
      />
      {showLabels && (
        <Layer
          id="sites-label"
          type="symbol"
          layout={{
            'text-font': LABEL_FONT,
            'text-field': ['coalesce', ['get', 'name'], ''],
            'text-size': 10,
            'text-offset': [0, 1.1],
            'text-anchor': 'top',
          }}
          paint={{ 'text-color': PALETTE.site, 'text-halo-color': '#ffffff', 'text-halo-width': 1.2 }}
        />
      )}
      <Layer
        id="sites-selected"
        type="circle"
        filter={selectedFilter(selectedFeatureId)}
        paint={{
          'circle-radius': pointRadius(8, 11),
          'circle-color': 'rgba(0, 0, 0, 0)',
          'circle-stroke-color': PALETTE.draft,
          'circle-stroke-width': 2.5,
        }}
      />
    </Source>
  );
}
