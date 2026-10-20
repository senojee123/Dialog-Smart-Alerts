import type { LngLatBoundsLike, StyleSpecification } from 'maplibre-gl';

import type { BBox, ServiceArea } from '../types/api';

/** Neutral style used until the Sri Lanka basemap (PMTiles, plan Section 8) is available. */
export const NEUTRAL_STYLE: StyleSpecification = {
  version: 8,
  name: 'GIS Core neutral background',
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#e8eef3' },
    },
  ],
};

/**
 * Font of the client's own labels. A label is drawn with the glyphs of the basemap style, so the basemap
 * must serve this font: the basemaps the reference data pipeline builds do (`fonts/Noto Sans Regular`).
 */
export const LABEL_FONT = ['Noto Sans Regular'];

export function resolveMapStyle(basemapStyleUrl: string | null): string | StyleSpecification {
  return basemapStyleUrl ?? NEUTRAL_STYLE;
}

/** Initial camera before the service area has loaded: Sri Lanka at country scale. */
export const INITIAL_VIEW = { longitude: 80.7, latitude: 7.85, zoom: 6.4 } as const;

/** A camera position: where the map is centred and how far it is zoomed in. */
export interface MapView {
  readonly longitude: number;
  readonly latitude: number;
  readonly zoom: number;
}

const VIEW_HASH = /^#map=(\d{1,2}(?:\.\d+)?)\/(-?\d{1,2}(?:\.\d+)?)\/(-?\d{1,3}(?:\.\d+)?)$/;

/**
 * The view named by a URL fragment `#map=<zoom>/<latitude>/<longitude>` (the order MapLibre and
 * OpenStreetMap use), so a view can be linked to. Anything else - including a position off the Earth or
 * a zoom MapLibre does not have - is ignored.
 */
export function parseViewHash(hash: string): MapView | null {
  const match = VIEW_HASH.exec(hash.trim());
  if (match === null) {
    return null;
  }
  const [zoom, latitude, longitude] = [Number(match[1]), Number(match[2]), Number(match[3])];
  if (zoom > 22 || Math.abs(latitude) > 85 || Math.abs(longitude) > 180) {
    return null;
  }
  return { longitude, latitude, zoom };
}

/** The fragment for a view, rounded to about a metre. */
export function viewHash(view: MapView): string {
  return `#map=${view.zoom.toFixed(2)}/${view.latitude.toFixed(5)}/${view.longitude.toFixed(5)}`;
}

export function bboxToBounds([minLon, minLat, maxLon, maxLat]: BBox): LngLatBoundsLike {
  return [
    [minLon, minLat],
    [maxLon, maxLat],
  ];
}

export function serviceAreaBounds(area: ServiceArea): LngLatBoundsLike {
  return bboxToBounds(area.properties.bbox);
}

export const SERVICE_AREA_SOURCE_ID = 'service-area';
export const SERVICE_AREA_FILL_LAYER_ID = 'service-area-fill';
export const SERVICE_AREA_LINE_LAYER_ID = 'service-area-outline';
