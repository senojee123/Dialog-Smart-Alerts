/**
 * Which panels the map client renders, and which MapLibre layers a click may select from.
 *
 * Separate from `MapContainer` so the component module exports only components (and so a host can decide
 * what to show without importing the component).
 */
import {
  DEVICE_LABEL_LAYER,
  DEVICE_POINT_LAYER,
  FIELD_OF_VIEW_FILL_LAYER,
  SITE_POINT_LAYER,
} from './layers/DeviceLayer';
import {
  EVENT_CLUSTER_LAYER,
  EVENT_HALO_LAYER,
  EVENT_POINT_LAYER,
  EVENT_SHAPE_FILL_LAYER,
  EVENT_SHAPE_LINE_LAYER,
} from './layers/EventLayer';
import { GEOFENCE_FILL_LAYER } from './layers/GeofenceLayer';
import {
  DEVICE_LAYER_ID,
  EVENT_LAYER_ID,
  FIELD_OF_VIEW_LAYER_ID,
  GEOFENCE_LAYER_ID,
  SITE_LAYER_ID,
  layerById,
  type MapLayerDefinition,
} from './layers/layerCatalogue';

export type PanelId = 'layers' | 'events' | 'tools' | 'editor' | 'export' | 'legend';

/**
 * Every panel. The map still shows a panel only when the caller may use it: the editor needs
 * `geofences:write`, the events panel `events:read`, the export panel `data:export` (see `access.ts`).
 */
export const ALL_PANELS: readonly PanelId[] = ['layers', 'events', 'tools', 'editor', 'export', 'legend'];

/** Event layers a click can select from; the cluster layer zooms into the cluster instead. */
const EVENT_INTERACTIVE_LAYER_IDS: readonly string[] = [
  // The halo is the larger click target around each event marker.
  EVENT_HALO_LAYER,
  EVENT_POINT_LAYER,
  EVENT_SHAPE_FILL_LAYER,
  EVENT_SHAPE_LINE_LAYER,
];

/** Which of a reference layer's MapLibre layers a click may select a feature from. */
function referenceInteractiveLayerIds(definition: MapLayerDefinition): readonly string[] {
  switch (definition.id) {
    case 'adminAreas':
    case 'protectedAreas':
    case 'riskZones':
      return [`${definition.id}-fill`];
    case 'waterBodies':
      return [`${definition.id}-fill`, `${definition.id}-line`];
    case 'roads':
      return [`${definition.id}-line`];
    case 'settlements':
      return [`${definition.id}-point`, `${definition.id}-fill`];
    case 'facilities':
      return [`${definition.id}-point`];
    default:
      return [];
  }
}

/** The MapLibre layers a click may select from, for the layers that are on. */
export function interactiveIdsFor(
  visible: ReadonlySet<string>,
  availableLayers: readonly MapLayerDefinition[],
  showLabels: boolean,
): readonly string[] {
  const known = new Set(availableLayers.map((layer) => layer.id));
  const ids: string[] = [];
  for (const layerId of visible) {
    if (!known.has(layerId)) {
      continue;
    }
    switch (layerId) {
      case EVENT_LAYER_ID:
        ids.push(...EVENT_INTERACTIVE_LAYER_IDS, EVENT_CLUSTER_LAYER);
        break;
      case DEVICE_LAYER_ID:
        ids.push(DEVICE_POINT_LAYER);
        if (showLabels) {
          ids.push(DEVICE_LABEL_LAYER);
        }
        break;
      case SITE_LAYER_ID:
        ids.push(SITE_POINT_LAYER);
        break;
      case GEOFENCE_LAYER_ID:
        ids.push(GEOFENCE_FILL_LAYER);
        break;
      case FIELD_OF_VIEW_LAYER_ID:
        ids.push(FIELD_OF_VIEW_FILL_LAYER);
        break;
      default: {
        const definition = layerById(layerId);
        if (definition !== undefined) {
          ids.push(...referenceInteractiveLayerIds(definition));
        }
      }
    }
  }
  return ids;
}
