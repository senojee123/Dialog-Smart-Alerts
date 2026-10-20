/**
 * Turning API features into MapLibre source data.
 *
 * The API already answers GeoJSON, so this is mostly bookkeeping: drop features whose geometry was not
 * requested, and carry the feature's identity and its layer in `properties` - a rendered feature that
 * comes back from a click keeps its properties, and that is how a click becomes a selection.
 */
import type { GeoJSONSourceSpecification } from 'react-map-gl/maplibre';

import { geometrySchema, type ApiFeature, type Geometry } from '../types/api';
import { pointInGeometry, positionsOf } from '../geo/geometry';
import type { Position } from '../geo/sld99';

/** Property names the client adds. Prefixed so they cannot collide with a layer's own attributes. */
export const FEATURE_ID_PROPERTY = '_featureId';
export const LAYER_ID_PROPERTY = '_layerId';

export interface SourceFeature {
  readonly type: 'Feature';
  readonly id?: string;
  readonly geometry: Geometry;
  readonly properties: Record<string, unknown>;
}

export interface SourceCollection {
  readonly type: 'FeatureCollection';
  readonly features: readonly SourceFeature[];
}

export const EMPTY_COLLECTION: SourceCollection = { type: 'FeatureCollection', features: [] };

/** What MapLibre accepts as a GeoJSON source's `data`. */
export type MapLibreSourceData = Exclude<NonNullable<GeoJSONSourceSpecification['data']>, string>;

/**
 * Hand source data to MapLibre.
 *
 * MapLibre's GeoJSON types describe mutable arrays; the client's geometry is read-only, which is the
 * stricter of the two. Nothing mutates a source: a change rebuilds it, so the conversion is safe and
 * this is the one place that states it.
 */
export function asSourceData(collection: SourceCollection): MapLibreSourceData {
  return collection as unknown as MapLibreSourceData;
}

/**
 * The geometry of a feature MapLibre handed back from a click, validated rather than asserted - the
 * rendered feature comes from the map's own store, and `GeometryCollection` is not something the API
 * produces.
 */
export function readGeometry(value: unknown): Geometry | null {
  const parsed = geometrySchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

/**
 * Source data for one layer's features.
 *
 * `extra` adds properties the paint expressions need but the API does not provide - the external state
 * of a device, for instance, which comes from another service entirely.
 */
export function toSourceData(
  layerId: string,
  features: readonly ApiFeature[],
  extra?: (feature: ApiFeature) => Record<string, unknown>,
): SourceCollection {
  const rendered: SourceFeature[] = [];
  for (const feature of features) {
    if (feature.geometry === null) {
      continue;
    }
    rendered.push({
      type: 'Feature',
      id: feature.id,
      geometry: feature.geometry,
      properties: {
        ...feature.properties,
        ...(extra === undefined ? {} : extra(feature)),
        [FEATURE_ID_PROPERTY]: feature.id,
        [LAYER_ID_PROPERTY]: layerId,
      },
    });
  }
  return { type: 'FeatureCollection', features: rendered };
}

/** One geometry as source data, for overlays: a measured line, a search circle, a drawn area. */
export function geometrySource(geometry: Geometry | null, properties: Record<string, unknown> = {}): SourceCollection {
  return geometry === null
    ? EMPTY_COLLECTION
    : { type: 'FeatureCollection', features: [{ type: 'Feature', geometry, properties }] };
}

export function positionsSource(
  positions: readonly Position[],
  properties: (position: Position, index: number) => Record<string, unknown> = () => ({}),
): SourceCollection {
  return {
    type: 'FeatureCollection',
    features: positions.map((position, index) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: position },
      properties: properties(position, index),
    })),
  };
}

/** Features that lie inside a drawn area: the client side of draw-to-filter. */
export function featuresInArea(features: readonly ApiFeature[], area: Geometry | null): readonly ApiFeature[] {
  if (area === null) {
    return features;
  }
  return features.filter((feature) => {
    if (feature.geometry === null) {
      return false;
    }
    if (feature.geometry.type === 'Point') {
      return pointInGeometry(feature.geometry.coordinates, area);
    }
    // Anything larger than a point counts when any of its positions is inside the area. The API is what
    // answers containment exactly (`POST /geo/v1/query/contains`); this only narrows what is drawn.
    return positionsOf(feature.geometry).some((position) => pointInGeometry(position, area));
  });
}
