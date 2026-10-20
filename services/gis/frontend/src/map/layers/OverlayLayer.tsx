/**
 * Everything drawn over the data: the ruler, the circle of a radius search, the results of a query, the
 * area drawn to filter by, and the geofence being edited.
 *
 * Circles are generated on the EPSG:5235 plane (`circlePolygon`), and a corridor is drawn as its centre
 * line with a width in metres, which is exactly what a round-capped line is. So what the operator sees
 * while drawing is the shape the service will store, not an approximation of it.
 */
import { Layer, Source } from 'react-map-gl/maplibre';

import { circlePolygon } from '../../geo/geometry';
import type { Position } from '../../geo/sld99';
import type { ApiFeature, Geometry } from '../../types/api';
import { FILL_OPACITY, PALETTE } from '../palette';
import { asSourceData, geometrySource, positionsSource, toSourceData } from '../sourceData';
import { draftAnchorLatitude, draftGeometry, type DraftShape } from './draftShape';
import { geometryFilter, metresAsPixels, pointRadius } from './styles';

export interface OverlayLayerProps {
  /** Positions of the ruler, in the order they were clicked. */
  readonly measure: readonly Position[];
  /** Labels for the ruler's positions (cumulative distance). */
  readonly measureLabels: readonly string[];
  readonly searchCircle: { readonly centre: Position; readonly radiusM: number } | null;
  readonly filterArea: Geometry | null;
  readonly results: readonly ApiFeature[];
  readonly draft: DraftShape | null;
}

const RESULTS_LAYER_ID = 'overlay-results';

export function OverlayLayer({
  measure,
  measureLabels,
  searchCircle,
  filterArea,
  results,
  draft,
}: OverlayLayerProps) {
  const circle = searchCircle === null ? null : circlePolygon(searchCircle.centre, searchCircle.radiusM);
  const measureLine: Geometry | null =
    measure.length >= 2 ? { type: 'LineString', coordinates: measure } : null;
  const draftLatitude = draftAnchorLatitude(draft);

  return (
    <>
      {filterArea !== null && (
        <Source id="overlay-filter-area" type="geojson" data={asSourceData(geometrySource(filterArea))}>
          <Layer
            id="overlay-filter-fill"
            type="fill"
            paint={{ 'fill-color': PALETTE.tool, 'fill-opacity': FILL_OPACITY.faint }}
          />
          <Layer
            id="overlay-filter-line"
            type="line"
            paint={{ 'line-color': PALETTE.tool, 'line-width': 2, 'line-dasharray': [2, 2] }}
          />
        </Source>
      )}

      {circle !== null && (
        <Source id="overlay-search-circle" type="geojson" data={asSourceData(geometrySource(circle))}>
          <Layer
            id="overlay-search-fill"
            type="fill"
            paint={{ 'fill-color': PALETTE.tool, 'fill-opacity': FILL_OPACITY.faint }}
          />
          <Layer
            id="overlay-search-line"
            type="line"
            paint={{ 'line-color': PALETTE.tool, 'line-width': 1.8 }}
          />
        </Source>
      )}

      <Source id="overlay-results" type="geojson" data={asSourceData(toSourceData(RESULTS_LAYER_ID, results))}>
        <Layer
          id="overlay-results-fill"
          type="fill"
          filter={geometryFilter('Polygon')}
          paint={{ 'fill-color': PALETTE.tool, 'fill-opacity': FILL_OPACITY.emphasis }}
        />
        <Layer
          id="overlay-results-line"
          type="line"
          filter={geometryFilter('LineString')}
          paint={{ 'line-color': PALETTE.tool, 'line-width': 3 }}
        />
        <Layer
          id="overlay-results-point"
          type="circle"
          filter={geometryFilter('Point')}
          paint={{
            'circle-radius': pointRadius(5, 9),
            'circle-color': 'rgba(0, 0, 0, 0)',
            'circle-stroke-color': PALETTE.tool,
            'circle-stroke-width': 2.5,
          }}
        />
      </Source>

      {draft !== null && (
        <Source id="overlay-draft" type="geojson" data={asSourceData(geometrySource(draftGeometry(draft)))}>
          <Layer
            id="overlay-draft-fill"
            type="fill"
            filter={geometryFilter('Polygon')}
            paint={{ 'fill-color': PALETTE.draft, 'fill-opacity': FILL_OPACITY.area }}
          />
          {draft.kind === 'corridor' && draft.radiusM !== null && (
            <Layer
              id="overlay-draft-corridor"
              type="line"
              layout={{ 'line-cap': 'round', 'line-join': 'round' }}
              paint={{
                'line-color': PALETTE.draft,
                'line-opacity': FILL_OPACITY.area,
                'line-width': metresAsPixels(draft.radiusM * 2, draftLatitude),
              }}
            />
          )}
          <Layer
            id="overlay-draft-line"
            type="line"
            paint={{ 'line-color': PALETTE.draft, 'line-width': 2, 'line-dasharray': [3, 1.5] }}
          />
          {/* A circle whose radius has been cleared is still somewhere: its centre stays on the map. */}
          <Layer
            id="overlay-draft-point"
            type="circle"
            filter={geometryFilter('Point')}
            paint={{
              'circle-radius': 5,
              'circle-color': '#ffffff',
              'circle-stroke-color': PALETTE.draft,
              'circle-stroke-width': 2.5,
            }}
          />
        </Source>
      )}

      {measureLine !== null && (
        <Source id="overlay-measure-line" type="geojson" data={asSourceData(geometrySource(measureLine))}>
          <Layer
            id="overlay-measure-path"
            type="line"
            layout={{ 'line-cap': 'round', 'line-join': 'round' }}
            paint={{ 'line-color': PALETTE.tool, 'line-width': 2.5, 'line-dasharray': [1.5, 1] }}
          />
        </Source>
      )}

      <Source
        id="overlay-measure-points"
        type="geojson"
        data={asSourceData(positionsSource(measure, (_position, index) => ({
          label: measureLabels[index] ?? '',
        })))}
      >
        <Layer
          id="overlay-measure-vertex"
          type="circle"
          paint={{
            'circle-radius': 4,
            'circle-color': '#ffffff',
            'circle-stroke-color': PALETTE.tool,
            'circle-stroke-width': 2,
          }}
        />
        <Layer
          id="overlay-measure-label"
          type="symbol"
          layout={{
            'text-field': ['get', 'label'],
            'text-size': 11,
            'text-offset': [0, -1.2],
            'text-anchor': 'bottom',
            'text-allow-overlap': true,
          }}
          paint={{ 'text-color': PALETTE.tool, 'text-halo-color': '#ffffff', 'text-halo-width': 1.4 }}
        />
      </Source>
    </>
  );
}
