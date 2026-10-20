/**
 * A stand-in for `GisApi`: every method rejects unless the test gives it an answer, so a test can only
 * pass by asking for what it says it asks for.
 */
import { vi } from 'vitest';

import type { GisApi } from '../services/gisApi';
import {
  administrator,
  emptyFeatureCollection,
  eventCollection,
  geofence,
  layerCatalogue,
  readyReport,
  reverseGeocode,
  serviceArea,
} from './fixtures';

export type ApiStub = {
  [Method in keyof GisApi]: ReturnType<typeof vi.fn>;
};

/** A stub whose reads answer the fixtures; override any method in the test. */
export function apiStub(overrides: Partial<Record<keyof GisApi, unknown>> = {}): GisApi & ApiStub {
  const stub = {
    getLiveness: vi.fn(() => Promise.resolve({ status: 'ok', service: 'gis-core-service', version: '0.1.0' })),
    getReadiness: vi.fn(() => Promise.resolve(readyReport)),
    getIdentity: vi.fn(() => Promise.resolve(administrator)),
    getServiceArea: vi.fn(() => Promise.resolve(serviceArea)),
    getLayerCatalogue: vi.fn(() => Promise.resolve(layerCatalogue)),
    listFeatures: vi.fn(() => Promise.resolve(emptyFeatureCollection)),
    listEvents: vi.fn(() => Promise.resolve(eventCollection([]))),
    queryWithinDistance: vi.fn(() => Promise.resolve(emptyFeatureCollection)),
    queryNearest: vi.fn(() => Promise.resolve(emptyFeatureCollection)),
    queryContains: vi.fn(() => Promise.resolve(emptyFeatureCollection)),
    reverseGeocode: vi.fn(() => Promise.resolve(reverseGeocode)),
    listGeofences: vi.fn(() => Promise.resolve({ items: [geofence], count: 1, nextCursor: null })),
    getGeofence: vi.fn(() => Promise.resolve(geofence)),
    createGeofence: vi.fn(() => Promise.resolve(geofence)),
    replaceGeofence: vi.fn(() => Promise.resolve({ ...geofence, version: geofence.version + 1 })),
    deleteGeofence: vi.fn(() => Promise.resolve()),
    listSites: vi.fn(() => Promise.resolve({ items: [], count: 0, nextCursor: null })),
    getSite: vi.fn(() => Promise.reject(new Error('no site'))),
    getDevicePlacement: vi.fn(() => Promise.reject(new Error('no device'))),
    exportFeatures: vi.fn(() => Promise.reject(new Error('no export'))),
    exportEvents: vi.fn(() => Promise.reject(new Error('no export'))),
    ...overrides,
  };
  return stub as unknown as GisApi & ApiStub;
}
