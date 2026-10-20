/**
 * Typed style fragments shared by the layer components: filters, colour ramps and the one place that
 * knows how to draw a width given in metres.
 */
import type {
  CircleLayerSpecification,
  FillLayerSpecification,
  LineLayerSpecification,
} from 'react-map-gl/maplibre';

import { FEATURE_ID_PROPERTY } from '../sourceData';

export type Filter = NonNullable<FillLayerSpecification['filter']>;
export type FillPaint = NonNullable<FillLayerSpecification['paint']>;
export type LinePaint = NonNullable<LineLayerSpecification['paint']>;
export type CirclePaint = NonNullable<CircleLayerSpecification['paint']>;
export type ColourValue = NonNullable<FillPaint['fill-color']>;
export type OpacityValue = NonNullable<FillPaint['fill-opacity']>;
export type NumberValue = NonNullable<LinePaint['line-width']>;

/** Matches the feature the operator selected, so a highlight can be drawn over it. */
export function selectedFilter(featureId: string | null): Filter {
  return ['==', ['get', FEATURE_ID_PROPERTY], featureId ?? '\u0000'];
}

/** MapLibre normalises Multi* geometries, so these three cover every feature. */
export function geometryFilter(kind: 'Point' | 'LineString' | 'Polygon'): Filter {
  return ['==', ['geometry-type'], kind];
}

/**
 * The selected feature, of one geometry kind: a highlight has to be drawn per kind, because a line
 * layer cannot outline a point.
 */
export function selectedGeometryFilter(
  featureId: string | null,
  kind: 'Point' | 'LineString' | 'Polygon',
): Filter {
  return [
    'all',
    ['==', ['get', FEATURE_ID_PROPERTY], featureId ?? '\u0000'],
    ['==', ['geometry-type'], kind],
  ];
}

/** Ground resolution in metres per pixel at the equator, zoom 0, for a 512 px tile scheme. */
const METRES_PER_PIXEL_AT_ZOOM_0 = 156543.03392 * (256 / 512);

/**
 * A width given in metres, expressed as pixels per zoom level.
 *
 * MapLibre paints line widths in pixels. Ground resolution halves with every zoom level, so an
 * exponential interpolation with base 2 between two anchors *is* the metres-to-pixels conversion,
 * exactly rather than approximately - at the given latitude.
 */
export function metresAsPixels(metres: number, latitude: number, minZoom = 4, maxZoom = 22): NumberValue {
  const pixelsAt = (zoom: number): number => {
    const resolution = (METRES_PER_PIXEL_AT_ZOOM_0 * Math.cos((latitude * Math.PI) / 180)) / 2 ** zoom;
    return metres / resolution;
  };
  return ['interpolate', ['exponential', 2], ['zoom'], minZoom, pixelsAt(minZoom), maxZoom, pixelsAt(maxZoom)];
}

/** Circle radius that grows with zoom, so points stay clickable when zoomed out and neat when in. */
export function pointRadius(small: number, large: number, from = 7, to = 14): NumberValue {
  return ['interpolate', ['linear'], ['zoom'], from, small, to, large];
}
