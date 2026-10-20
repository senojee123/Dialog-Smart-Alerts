/**
 * The map's own state: what the operator is doing, what is selected, what is filtered.
 *
 * Pure types and pure functions - the components hold this state, the hooks derive requests from it.
 */
import type { Geometry } from '../../types/api';
import type { Position } from '../../geo/sld99';

/**
 * What a click on the map means.
 *
 * * `select` - inspect the feature that was clicked (the default)
 * * `measure` - add a position to the ruler
 * * `radius` - place the centre of a radius search
 * * `nearby` - place the point to find the nearest devices from
 * * `drawFilter` - drawing an area to filter the map to
 * * `drawGeofence` - drawing a geofence in the editor
 */
export type InteractionMode = 'select' | 'measure' | 'radius' | 'nearby' | 'drawFilter' | 'drawGeofence';

/** Modes in which Terra Draw owns the pointer, so the map's own click handling stands back. */
export const DRAWING_MODES: readonly InteractionMode[] = ['drawFilter', 'drawGeofence'];

export function isDrawing(mode: InteractionMode): boolean {
  return DRAWING_MODES.includes(mode);
}

export interface Selection {
  readonly layerId: string;
  readonly featureId: string;
  readonly properties: Readonly<Record<string, unknown>>;
  readonly geometry: Geometry | null;
  /** Where the popup is anchored: the clicked position. */
  readonly position: Position;
}

export interface EventFilterState {
  /** Event type, exactly as the events carry it (`wildlife.elephant_detected`). */
  readonly eventType: string | null;
  readonly sourceType: string | null;
  /** Width of the window in hours, used when neither end is pinned. */
  readonly windowHours: number;
  /** Pinned start and end (ISO 8601); both `null` means "the last `windowHours`". */
  readonly from: string | null;
  readonly to: string | null;
}

export interface TimeWindow {
  readonly from: string;
  readonly to: string;
}

/** `GET /geo/v1/events` refuses a window longer than this. */
export const MAX_EVENT_WINDOW_DAYS = 31;
const HOUR_MS = 3_600_000;

export function defaultEventFilters(windowHours: number): EventFilterState {
  return { eventType: null, sourceType: null, windowHours, from: null, to: null };
}

/**
 * The window to ask for. A relative window is resolved against `now` at request time, so it follows the
 * clock; a pinned window is left alone, which is what lets an operator page through it.
 */
export function eventWindow(filters: EventFilterState, now: Date): TimeWindow {
  const to = filters.to ?? now.toISOString();
  const end = new Date(to);
  const from = filters.from ?? new Date(end.getTime() - filters.windowHours * HOUR_MS).toISOString();
  return { from, to };
}

export function windowHours(window: TimeWindow): number {
  return (new Date(window.to).getTime() - new Date(window.from).getTime()) / HOUR_MS;
}

export function windowIsTooLong(window: TimeWindow): boolean {
  return windowHours(window) > MAX_EVENT_WINDOW_DAYS * 24;
}

/** Window presets an operator reaches for, in hours. */
export const WINDOW_PRESETS: readonly { readonly label: string; readonly hours: number }[] = [
  { label: '1 h', hours: 1 },
  { label: '6 h', hours: 6 },
  { label: '24 h', hours: 24 },
  { label: '7 d', hours: 24 * 7 },
  { label: '31 d', hours: 24 * 31 },
];

/** An area drawn to filter the map to, with the bounds the requests are narrowed by. */
export interface FilterArea {
  readonly geometry: Geometry;
}
