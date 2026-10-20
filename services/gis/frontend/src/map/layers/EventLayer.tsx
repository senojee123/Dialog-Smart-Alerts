/**
 * Event locations.
 *
 * Events arrive as points far more often than not, and in a busy window there are thousands of them in
 * one town, so the point source clusters: MapLibre groups them below the zoom at which they separate,
 * and a click on a cluster zooms into it. Events with a line or area geometry - a track, a sighting
 * area - are drawn in a second, unclustered source, because a cluster of areas would mean nothing.
 *
 * Events are what an operator looks for first, so they are drawn to be found at any zoom: a marker with a
 * white outline over a soft halo, and the halo - several times the marker's area - is what a click hits.
 */
import { Layer, Source } from 'react-map-gl/maplibre';

import type { ApiFeature } from '../../types/api';
import { LABEL_FONT } from '../mapStyle';
import { PALETTE } from '../palette';
import { asSourceData, toSourceData } from '../sourceData';
import { EVENT_LAYER_ID } from './layerCatalogue';
import { geometryFilter, pointRadius, selectedFilter, type ColourValue, type NumberValue } from './styles';

export const EVENT_POINT_SOURCE = 'events-points';
export const EVENT_SHAPE_SOURCE = 'events-shapes';
export const EVENT_CLUSTER_LAYER = 'events-clusters';
export const EVENT_CLUSTER_COUNT_LAYER = 'events-cluster-count';
export const EVENT_POINT_LAYER = 'events-point';
/** The soft halo under each event: it makes the event easy to see and is its (larger) click target. */
export const EVENT_HALO_LAYER = 'events-point-halo';
export const EVENT_CLUSTER_HALO_LAYER = 'events-clusters-halo';
export const EVENT_SHAPE_FILL_LAYER = 'events-shape-fill';
export const EVENT_SHAPE_LINE_LAYER = 'events-shape-line';

const CLUSTER_COLOUR: ColourValue = [
  'step',
  ['get', 'point_count'],
  PALETTE.eventCluster,
  10,
  PALETTE.event,
  50,
  PALETTE.eventSelected,
];

// Sizes in pixels from country scale (zoom 5) to street scale (zoom 14): visible when zoomed out,
// not covering the street when zoomed in.
const MARKER_RADIUS = pointRadius(7, 10, 5, 14);
const HALO_RADIUS = pointRadius(15, 20, 5, 14);
const CLUSTER_RADIUS: NumberValue = ['step', ['get', 'point_count'], 17, 10, 21, 50, 27];
const CLUSTER_HALO_RADIUS: NumberValue = ['step', ['get', 'point_count'], 24, 10, 28, 50, 34];

export interface EventLayerProps {
  readonly features: readonly ApiFeature[];
  readonly selectedFeatureId: string | null;
}

export function EventLayer({ features, selectedFeatureId }: EventLayerProps) {
  const points = features.filter((feature) => feature.geometry?.type === 'Point');
  const shapes = features.filter(
    (feature) => feature.geometry !== null && feature.geometry.type !== 'Point',
  );
  const highlight = selectedFilter(selectedFeatureId);

  return (
    <>
      <Source
        id={EVENT_SHAPE_SOURCE}
        type="geojson"
        data={asSourceData(toSourceData(EVENT_LAYER_ID, shapes))}
      >
        <Layer
          id={EVENT_SHAPE_FILL_LAYER}
          type="fill"
          filter={geometryFilter('Polygon')}
          paint={{ 'fill-color': PALETTE.event, 'fill-opacity': 0.2 }}
        />
        <Layer
          id={EVENT_SHAPE_LINE_LAYER}
          type="line"
          paint={{ 'line-color': PALETTE.event, 'line-width': 2 }}
        />
        {/* An event that is a track or an area is selected like any other, so it is marked like one. */}
        <Layer
          id="events-shape-selected"
          type="line"
          filter={highlight}
          paint={{ 'line-color': PALETTE.eventSelected, 'line-width': 4 }}
        />
      </Source>

      <Source
        id={EVENT_POINT_SOURCE}
        type="geojson"
        data={asSourceData(toSourceData(EVENT_LAYER_ID, points))}
        cluster
        clusterRadius={50}
        clusterMaxZoom={15}
      >
        <Layer
          id={EVENT_CLUSTER_HALO_LAYER}
          type="circle"
          filter={['has', 'point_count']}
          paint={{
            'circle-color': CLUSTER_COLOUR,
            'circle-radius': CLUSTER_HALO_RADIUS,
            'circle-opacity': 0.22,
            'circle-blur': 0.3,
          }}
        />
        <Layer
          id={EVENT_CLUSTER_LAYER}
          type="circle"
          filter={['has', 'point_count']}
          paint={{
            'circle-color': CLUSTER_COLOUR,
            'circle-radius': CLUSTER_RADIUS,
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 2.5,
          }}
        />
        <Layer
          id={EVENT_CLUSTER_COUNT_LAYER}
          type="symbol"
          filter={['has', 'point_count']}
          layout={{
            'text-font': LABEL_FONT,
            'text-field': ['get', 'point_count_abbreviated'],
            'text-size': 13,
            'text-allow-overlap': true,
          }}
          paint={{ 'text-color': '#ffffff', 'text-halo-color': 'rgba(0, 0, 0, 0.25)', 'text-halo-width': 1 }}
        />
        <Layer
          id={EVENT_HALO_LAYER}
          type="circle"
          filter={['!', ['has', 'point_count']]}
          paint={{
            'circle-radius': HALO_RADIUS,
            'circle-color': PALETTE.event,
            'circle-opacity': 0.2,
            'circle-blur': 0.35,
          }}
        />
        <Layer
          id={EVENT_POINT_LAYER}
          type="circle"
          filter={['!', ['has', 'point_count']]}
          paint={{
            'circle-radius': MARKER_RADIUS,
            'circle-color': PALETTE.event,
            'circle-stroke-color': '#ffffff',
            'circle-stroke-width': 2.5,
          }}
        />
        <Layer
          id="events-selected"
          type="circle"
          filter={highlight}
          paint={{
            'circle-radius': pointRadius(13, 16, 5, 14),
            'circle-color': 'rgba(0, 0, 0, 0)',
            'circle-stroke-color': PALETTE.eventSelected,
            'circle-stroke-width': 3.5,
          }}
        />
      </Source>
    </>
  );
}
