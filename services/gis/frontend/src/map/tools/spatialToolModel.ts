/**
 * The spatial tools, as values and functions: what a tool asks the API, and how its answer reads.
 *
 * Every tool is a generic geographic question - what is within this distance, what is nearest, how far
 * is this from that, what is inside the area I drew. None of them is a question about people.
 */
import { formatMetres } from '../editor/geofenceDraft';
import { pathLengthM, type Position } from '../../geo/sld99';
import type { ApiFeature, FeatureCollection, LayerCatalogue, LayerSummary } from '../../types/api';

export type ToolId = 'radius' | 'nearby' | 'measure' | 'filter';

export const DEVICE_LAYER_CODE = 'ops.device';

export const RADIUS_PRESETS: readonly number[] = [250, 500, 1000, 2500, 5000, 10_000];
export const DEFAULT_RADIUS_M = 1000;
export const MAX_RADIUS_M = 100_000;
export const DEFAULT_NEAREST_LIMIT = 10;
export const MAX_NEAREST_LIMIT = 100;
export const DEFAULT_NEAREST_MAX_DISTANCE_M = 25_000;

export interface ResultRow {
  readonly id: string;
  readonly name: string;
  readonly distanceM: number | null;
  readonly relation: string | null;
  readonly position: Position | null;
  readonly detail: string | null;
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

function firstPosition(feature: ApiFeature): Position | null {
  const geometry = feature.geometry;
  if (geometry === null) {
    return null;
  }
  switch (geometry.type) {
    case 'Point':
      return geometry.coordinates;
    case 'MultiPoint':
    case 'LineString':
      return geometry.coordinates[0] ?? null;
    case 'MultiLineString':
    case 'Polygon':
      return geometry.coordinates[0]?.[0] ?? null;
    case 'MultiPolygon':
      return geometry.coordinates[0]?.[0]?.[0] ?? null;
  }
}

/** A query answer as rows an operator can read: name, distance and something to identify it by. */
export function resultRows(collection: FeatureCollection): readonly ResultRow[] {
  return collection.features.map((feature) => {
    const properties = feature.properties;
    const distance = properties.distanceM;
    return {
      id: feature.id,
      name: text(properties.name) ?? feature.id,
      distanceM: typeof distance === 'number' ? distance : null,
      relation: text(properties.relation),
      position: firstPosition(feature),
      detail:
        text(properties.deviceType) ??
        text(properties.settlementType) ??
        text(properties.facilityType) ??
        text(properties.siteType) ??
        text(properties.class) ??
        text(properties.designation) ??
        text(properties.status),
    };
  });
}

/** Cumulative distance at each position of a measured path, formatted for the map labels. */
export function cumulativeLabels(positions: readonly Position[]): readonly string[] {
  return positions.map((_position, index) => {
    if (index === 0) {
      return 'start';
    }
    return formatMetres(pathLengthM(positions.slice(0, index + 1)));
  });
}

export function totalLengthM(positions: readonly Position[]): number {
  return pathLengthM(positions);
}

/** Layers the service says can answer a given kind of query. */
export function targetsFor(
  catalogue: LayerCatalogue | null,
  capability: 'within_distance' | 'nearest' | 'contains',
): readonly LayerSummary[] {
  return (catalogue?.layers ?? []).filter(
    (layer) => layer.queryable && layer.capabilities.includes(capability),
  );
}

/** What a radius search looks for unless the operator chooses otherwise. */
const PREFERRED_TARGETS: readonly string[] = ['ref.facility', 'ref.settlement', DEVICE_LAYER_CODE];

export function defaultTarget(catalogue: LayerCatalogue | null): string {
  const targets = targetsFor(catalogue, 'within_distance');
  for (const preferred of PREFERRED_TARGETS) {
    if (targets.some((layer) => layer.code === preferred)) {
      return preferred;
    }
  }
  return targets[0]?.code ?? 'ref.settlement';
}

export const TOOL_LABELS: Readonly<Record<ToolId, string>> = {
  radius: 'Radius search',
  nearby: 'Nearby devices',
  measure: 'Measure',
  filter: 'Draw to filter',
};

export const TOOL_HINTS: Readonly<Record<ToolId, string>> = {
  radius: 'Click the map to search around a position.',
  nearby: 'Click the map to find the devices nearest to it.',
  measure: 'Click along the path to measure it; the distance is in EPSG:5235 metres.',
  filter: 'Draw an area; the map then shows only what lies inside it.',
};
