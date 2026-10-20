/**
 * What the map offers, from what the caller may do (`GET /geo/v1/me`).
 *
 * The API checks every request itself; this is about not offering what it would refuse - a "New
 * geofence" button for a viewer, an event layer that can only ever answer 403. Until the answer is known
 * (or if it cannot be had), the map still attempts reads, because the API decides those, and offers
 * nothing that changes or exports data.
 */
import type { Identity, Permission } from '../types/api';

export interface Abilities {
  /** Whether the caller's permissions are known. */
  readonly known: boolean;
  readonly editGeofences: boolean;
  readonly readEvents: boolean;
  readonly askSpatialQuestions: boolean;
  readonly exportData: boolean;
}

export const UNKNOWN_ABILITIES: Abilities = {
  known: false,
  editGeofences: false,
  readEvents: true,
  askSpatialQuestions: true,
  exportData: false,
};

export function abilitiesOf(identity: Identity | null): Abilities {
  if (identity === null) {
    return UNKNOWN_ABILITIES;
  }
  const has = (permission: Permission): boolean => identity.permissions.includes(permission);
  return {
    known: true,
    editGeofences: has('geofences:write'),
    readEvents: has('events:read'),
    askSpatialQuestions: has('query:spatial'),
    exportData: has('data:export'),
  };
}
