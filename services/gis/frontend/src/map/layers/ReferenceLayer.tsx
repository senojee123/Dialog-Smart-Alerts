/**
 * Reference layers: administrative areas, protected areas, risk zones, water, roads, settlements and
 * facilities. One component, because they differ only in how they are painted - what they mean, and
 * which of them a deployment has, is the service's business (`GET /geo/v1/layers`).
 */
import { Layer, Source } from 'react-map-gl/maplibre';

import type { ApiFeature } from '../../types/api';
import { LABEL_FONT } from '../mapStyle';
import { FILL_OPACITY, PALETTE } from '../palette';
import { asSourceData, toSourceData } from '../sourceData';
import type { MapLayerDefinition } from './layerCatalogue';
import {
  geometryFilter,
  pointRadius,
  selectedGeometryFilter,
  type ColourValue,
  type NumberValue,
} from './styles';

export interface ReferenceLayerProps {
  readonly definition: MapLayerDefinition;
  readonly features: readonly ApiFeature[];
  readonly selectedFeatureId: string | null;
  readonly showLabels: boolean;
}

const RISK_COLOUR: ColourValue = [
  'step',
  ['coalesce', ['to-number', ['get', 'severity']], 1],
  '#fdba74',
  3,
  '#fb923c',
  4,
  PALETTE.riskZone,
];

const ROAD_COLOUR: ColourValue = [
  'match',
  ['get', 'class'],
  'A',
  '#3f3f46',
  'B',
  PALETTE.road,
  '#a1a1aa',
];

const ROAD_WIDTH: NumberValue = [
  'interpolate',
  ['linear'],
  ['zoom'],
  9,
  ['match', ['get', 'class'], 'A', 1.6, 'B', 1.2, 0.7],
  16,
  ['match', ['get', 'class'], 'A', 5, 'B', 3.5, 2],
];

const ADMIN_WIDTH: NumberValue = [
  'interpolate',
  ['linear'],
  ['zoom'],
  6,
  ['match', ['to-number', ['get', 'level']], 1, 1.4, 2, 1, 0.6],
  14,
  ['match', ['to-number', ['get', 'level']], 1, 3, 2, 2, 1.2],
];

export function ReferenceLayer({
  definition,
  features,
  selectedFeatureId,
  showLabels,
}: ReferenceLayerProps) {
  const sourceId = `${definition.id}-source`;
  const data = toSourceData(definition.id, features);

  return (
    // Layers are direct children, or arrays of them: react-map-gl hands the source id to each child, and
    // a fragment would swallow it.
    <Source id={sourceId} type="geojson" data={asSourceData(data)}>
      {definition.id === 'adminAreas' && [
        <Layer
          key="fill"
          id={`${definition.id}-fill`}
          type="fill"
          paint={{ 'fill-color': PALETTE.adminBoundary, 'fill-opacity': FILL_OPACITY.faint / 2 }}
        />,
        <Layer
          key="line"
          id={`${definition.id}-line`}
          type="line"
          paint={{
            'line-color': PALETTE.adminBoundary,
            'line-width': ADMIN_WIDTH,
            'line-dasharray': [4, 2],
          }}
        />,
      ]}

      {definition.id === 'protectedAreas' && [
        <Layer
          key="fill"
          id={`${definition.id}-fill`}
          type="fill"
          paint={{ 'fill-color': PALETTE.protectedArea, 'fill-opacity': FILL_OPACITY.area }}
        />,
        <Layer
          key="line"
          id={`${definition.id}-line`}
          type="line"
          paint={{ 'line-color': PALETTE.protectedArea, 'line-width': 1.2 }}
        />,
      ]}

      {definition.id === 'riskZones' && [
        <Layer
          key="fill"
          id={`${definition.id}-fill`}
          type="fill"
          paint={{ 'fill-color': RISK_COLOUR, 'fill-opacity': FILL_OPACITY.emphasis }}
        />,
        <Layer
          key="line"
          id={`${definition.id}-line`}
          type="line"
          paint={{ 'line-color': RISK_COLOUR, 'line-width': 1.2, 'line-dasharray': [2, 1] }}
        />,
      ]}

      {definition.id === 'waterBodies' && [
        <Layer
          key="fill"
          id={`${definition.id}-fill`}
          type="fill"
          filter={geometryFilter('Polygon')}
          paint={{ 'fill-color': PALETTE.water, 'fill-opacity': FILL_OPACITY.emphasis }}
        />,
        <Layer
          key="line"
          id={`${definition.id}-line`}
          type="line"
          paint={{ 'line-color': PALETTE.water, 'line-width': 1.4 }}
        />,
      ]}

      {definition.id === 'roads' && (
        <Layer
          id={`${definition.id}-line`}
          type="line"
          layout={{ 'line-cap': 'round', 'line-join': 'round' }}
          paint={{ 'line-color': ROAD_COLOUR, 'line-width': ROAD_WIDTH }}
        />
      )}

      {definition.id === 'settlements' && [
        <Layer
          key="fill"
          id={`${definition.id}-fill`}
          type="fill"
          filter={geometryFilter('Polygon')}
          paint={{ 'fill-color': PALETTE.settlement, 'fill-opacity': FILL_OPACITY.area }}
        />,
        <Layer
          key="outline"
          id={`${definition.id}-outline`}
          type="line"
          filter={geometryFilter('Polygon')}
          paint={{ 'line-color': PALETTE.settlement, 'line-width': 1 }}
        />,
        <Layer
          key="point"
          id={`${definition.id}-point`}
          type="circle"
          filter={geometryFilter('Point')}
          paint={{
            'circle-radius': pointRadius(2.5, 5),
            'circle-color': PALETTE.settlement,
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 1,
          }}
        />,
      ]}

      {definition.id === 'facilities' && (
        <Layer
          id={`${definition.id}-point`}
          type="circle"
          paint={{
            'circle-radius': pointRadius(3, 6),
            'circle-color': PALETTE.facility,
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 1,
          }}
        />
      )}

      {showLabels && (
        <Layer
          id={`${definition.id}-label`}
          type="symbol"
          filter={geometryFilter('Point')}
          layout={{
            'text-font': LABEL_FONT,
            'text-field': ['coalesce', ['get', 'name'], ''],
            'text-size': 11,
            'text-offset': [0, 1.1],
            'text-anchor': 'top',
            'text-allow-overlap': false,
          }}
          paint={{ 'text-color': '#1f2937', 'text-halo-color': '#ffffff', 'text-halo-width': 1.2 }}
        />
      )}

      <Layer
        id={`${definition.id}-selected-area`}
        type="line"
        filter={selectedGeometryFilter(selectedFeatureId, 'Polygon')}
        paint={{ 'line-color': PALETTE.draft, 'line-width': 3 }}
      />
      <Layer
        id={`${definition.id}-selected-line`}
        type="line"
        filter={selectedGeometryFilter(selectedFeatureId, 'LineString')}
        paint={{ 'line-color': PALETTE.draft, 'line-width': 4, 'line-opacity': 0.7 }}
      />
      <Layer
        id={`${definition.id}-selected-point`}
        type="circle"
        filter={selectedGeometryFilter(selectedFeatureId, 'Point')}
        paint={{
          'circle-radius': pointRadius(6, 10),
          'circle-color': 'rgba(0, 0, 0, 0)',
          'circle-stroke-color': PALETTE.draft,
          'circle-stroke-width': 2.5,
        }}
      />
    </Source>
  );
}
