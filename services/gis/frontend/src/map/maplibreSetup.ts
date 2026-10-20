/**
 * One-time MapLibre GL JS setup (ADR-07: MapLibre v6).
 *
 * * v6 ships ES modules only; bundlers must tell it where its web worker lives.
 * * The `pmtiles://` protocol lets a style read vector tiles straight from a PMTiles file with HTTP
 *   range requests, which is how the MVP basemap is served (plan Section 8).
 */
import * as maplibregl from 'maplibre-gl';
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Protocol } from 'pmtiles';

let configured = false;

export function configureMapLibre(): typeof maplibregl {
  if (!configured) {
    maplibregl.setWorkerUrl(maplibreWorkerUrl);
    const pmtiles = new Protocol();
    maplibregl.addProtocol('pmtiles', pmtiles.tile);
    configured = true;
  }
  return maplibregl;
}

/** MapLibre v6 requires WebGL2 (plan risk R8). */
export function supportsWebGL2(doc: Document = document): boolean {
  try {
    const canvas = doc.createElement('canvas');
    return canvas.getContext('webgl2') !== null;
  } catch {
    return false;
  }
}
