/**
 * Geofences: the areas a tenant maintains.
 *
 * The API serves the polygon the database derives from a geofence's definition, which is what is drawn
 * here. The definition itself - a polygon, or a centre and a radius - is what the editor works with and
 * what the service tests hits against; the two agree to within the centimetre the API rounds to.
 *
 * A geofence is an area on a map. What follows from something happening inside it belongs to the
 * services that consume the geo-context, not to this map (ADR-0012).
 */
import { useMemo } from 'react';
import { Layer, Source } from 'react-map-gl/maplibre';

import type { ApiFeature } from '../../types/api';
import { LABEL_FONT } from '../mapStyle';
import { FILL_OPACITY, PALETTE } from '../palette';
import { asSourceData, toSourceData } from '../sourceData';
import { GEOFENCE_LAYER_ID } from './layerCatalogue';
import { selectedFilter, type ColourValue, type Filter, type OpacityValue } from './styles';

export const GEOFENCE_FILL_LAYER = 'geofences-fill';
export const GEOFENCE_LINE_LAYER = 'geofences-line';

const STATUS_COLOUR: ColourValue = [
  'match',
  ['get', 'status'],
  'active',
  PALETTE.geofence,
  'draft',
  PALETTE.geofenceDraft,
  'suspended',
  PALETTE.geofenceSuspended,
  PALETTE.geofenceSuspended,
];

/** Only an active geofence produces geo-context hits, so only an active one is drawn solidly. */
const STATUS_OPACITY: OpacityValue = [
  'match',
  ['get', 'status'],
  'active',
  FILL_OPACITY.area,
  FILL_OPACITY.faint,
];

const IS_ACTIVE: Filter = ['==', ['get', 'status'], 'active'];
const IS_NOT_ACTIVE: Filter = ['!=', ['get', 'status'], 'active'];

export interface GeofenceLayerProps {
  readonly features: readonly ApiFeature[];
  readonly selectedFeatureId: string | null;
  readonly showLabels: boolean;
}

export function GeofenceLayer({ features, selectedFeatureId, showLabels }: GeofenceLayerProps) {
  // An archived geofence is retired: it is kept because stored hits name it, but it is not part of the
  // operational picture, and the legend has no entry for it.
  const current = useMemo(
    () => features.filter((feature) => feature.properties.status !== 'archived'),
    [features],
  );
  return (
    <Source
      id="geofences-source"
      type="geojson"
      data={asSourceData(toSourceData(GEOFENCE_LAYER_ID, current))}
    >
      <Layer
        id={GEOFENCE_FILL_LAYER}
        type="fill"
        paint={{ 'fill-color': STATUS_COLOUR, 'fill-opacity': STATUS_OPACITY }}
      />
      <Layer
        id={GEOFENCE_LINE_LAYER}
        type="line"
        filter={IS_ACTIVE}
        paint={{ 'line-color': STATUS_COLOUR, 'line-width': 1.6 }}
      />
      {/* A geofence that is not active is drawn dashed: it is stored, but it produces no hits. */}
      <Layer
        id="geofences-line-inactive"
        type="line"
        filter={IS_NOT_ACTIVE}
        paint={{ 'line-color': STATUS_COLOUR, 'line-width': 1.4, 'line-dasharray': [3, 2] }}
      />
      {showLabels && (
        <Layer
          id="geofences-label"
          type="symbol"
          layout={{
            'text-font': LABEL_FONT,
            'text-field': ['coalesce', ['get', 'name'], ''],
            'text-size': 11,
            'symbol-placement': 'point',
          }}
          paint={{ 'text-color': PALETTE.geofence, 'text-halo-color': '#ffffff', 'text-halo-width': 1.4 }}
        />
      )}
      <Layer
        id="geofences-selected"
        type="line"
        filter={selectedFilter(selectedFeatureId)}
        paint={{ 'line-color': PALETTE.draft, 'line-width': 3 }}
      />
    </Source>
  );
}
