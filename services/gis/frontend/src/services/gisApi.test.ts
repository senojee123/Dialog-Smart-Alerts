import { describe, expect, it } from 'vitest';

import { fetchStub, parametersOf, pathOf } from '../test/fetchStub';
import { createGisApi } from './gisApi';
import { emptyFeatureCollection, geofence, layerCatalogue, reverseGeocode } from '../test/fixtures';

function api(stub: ReturnType<typeof fetchStub>) {
  return createGisApi({ baseUrl: '/api', fetchImpl: stub.fetch, tenantId: null });
}

describe('layers and features', () => {
  it('reads the catalogue for a tenant', async () => {
    const stub = fetchStub({ body: layerCatalogue });
    const answer = await api(stub).getLayerCatalogue({ tenantId: 'wildlife-dept' });
    expect(pathOf(stub.last())).toBe('/api/geo/v1/layers');
    expect(parametersOf(stub.last())).toEqual({ tenantId: 'wildlife-dept' });
    expect(answer.layers.map((layer) => layer.code)).toContain('ref.settlement');
  });

  it('asks for a layer window with its filters, bbox and paging', async () => {
    const stub = fetchStub({ body: emptyFeatureCollection });
    await api(stub).listFeatures({
      layer: 'ref.settlement',
      bounds: [80.6, 7.9, 80.9, 8.2],
      filters: { type: 'town', level: null },
      nameContains: 'Haba',
      includeGeometry: true,
      limit: 250,
      cursor: 'eyJrIjoi',
      tenantId: null,
    });
    expect(pathOf(stub.last())).toBe('/api/geo/v1/layers/ref.settlement/features');
    expect(parametersOf(stub.last())).toEqual({
      type: 'town',
      bbox: '80.6,7.9,80.9,8.2',
      nameContains: 'Haba',
      includeGeometry: 'true',
      limit: '250',
      cursor: 'eyJrIjoi',
    });
  });

  it('escapes a layer code in the path', async () => {
    const stub = fetchStub({ body: emptyFeatureCollection });
    await api(stub).listFeatures({ layer: 'ops.device_field_of_view' });
    expect(pathOf(stub.last())).toBe('/api/geo/v1/layers/ops.device_field_of_view/features');
  });
});

describe('spatial queries', () => {
  it('posts a within-distance query with the tenant on the query string', async () => {
    const stub = fetchStub({ body: emptyFeatureCollection });
    await api(stub).queryWithinDistance({
      target: 'ref.facility',
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
      distanceM: 5000,
      filters: { type: 'hospital', status: null },
      tenantId: 'wildlife-dept',
      limit: 50,
    });
    expect(pathOf(stub.last())).toBe('/api/geo/v1/query/within-distance');
    expect(parametersOf(stub.last())).toEqual({ tenantId: 'wildlife-dept' });
    expect(stub.last().body).toEqual({
      target: 'ref.facility',
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
      filters: { type: 'hospital' },
      distanceM: 5000,
      limit: 50,
    });
  });

  it('leaves filters out of the body when none were set', async () => {
    const stub = fetchStub({ body: emptyFeatureCollection });
    await api(stub).queryNearest({
      target: 'ops.device',
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
      limit: 5,
      maxDistanceM: 10_000,
    });
    expect(stub.last().body).toEqual({
      target: 'ops.device',
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
      maxDistanceM: 10_000,
      limit: 5,
    });
  });

  it('posts a containment query with its mode', async () => {
    const stub = fetchStub({ body: emptyFeatureCollection });
    await api(stub).queryContains({
      target: 'ref.protected_area',
      geometry: { type: 'Point', coordinates: [80.758, 8.015] },
      mode: 'intersects',
    });
    expect(pathOf(stub.last())).toBe('/api/geo/v1/query/contains');
    expect(stub.last().body).toMatchObject({ mode: 'intersects' });
  });

  it('reverse geocodes a position', async () => {
    const stub = fetchStub({ body: reverseGeocode });
    const answer = await api(stub).reverseGeocode([80.7513, 8.0342]);
    expect(pathOf(stub.last())).toBe('/api/geo/v1/reverse');
    expect(parametersOf(stub.last())).toEqual({ lon: '80.7513', lat: '8.0342' });
    expect(answer.admin.district?.name).toBe('Anuradhapura');
    expect(answer.nearestSettlement?.distanceM).toBeCloseTo(512.34, 2);
  });
});

describe('events', () => {
  it('asks for a window, a viewport and the filters that were set', async () => {
    const stub = fetchStub({
      body: { ...emptyFeatureCollection, window: { from: '2026-09-14T00:00:00Z', to: '2026-09-15T00:00:00Z' } },
    });
    const answer = await api(stub).listEvents({
      from: '2026-09-14T00:00:00Z',
      to: '2026-09-15T00:00:00Z',
      bounds: [80.6, 7.9, 80.9, 8.2],
      eventType: 'wildlife.elephant_detected',
      sourceType: null,
      tenantId: 'wildlife-dept',
      limit: 100,
    });
    expect(pathOf(stub.last())).toBe('/api/geo/v1/events');
    expect(parametersOf(stub.last())).toEqual({
      from: '2026-09-14T00:00:00Z',
      to: '2026-09-15T00:00:00Z',
      bbox: '80.6,7.9,80.9,8.2',
      eventType: 'wildlife.elephant_detected',
      tenantId: 'wildlife-dept',
      limit: '100',
    });
    expect(answer.window.from).toBe('2026-09-14T00:00:00Z');
  });
});

describe('geofences', () => {
  it('lists with the filters the service accepts', async () => {
    const stub = fetchStub({ body: { items: [geofence], count: 1, nextCursor: null } });
    const answer = await api(stub).listGeofences({
      status: 'active',
      kind: 'circle',
      bounds: [80.6, 7.9, 80.9, 8.2],
      ownedOnly: true,
      tenantId: 'wildlife-dept',
    });
    expect(parametersOf(stub.last())).toEqual({
      status: 'active',
      kind: 'circle',
      bbox: '80.6,7.9,80.9,8.2',
      ownedOnly: 'true',
      tenantId: 'wildlife-dept',
    });
    expect(answer.items[0]?.definition.radiusM).toBe(750);
  });

  it('creates and expects 201', async () => {
    const stub = fetchStub({ status: 201, body: geofence });
    const created = await api(stub).createGeofence(
      {
        name: 'Habarana junction watch zone',
        definition: { kind: 'circle', geometry: { type: 'Point', coordinates: [80.7487, 8.0356] }, radiusM: 750 },
      },
      { tenantId: 'wildlife-dept' },
    );
    expect(stub.last().method).toBe('POST');
    expect(created.version).toBe(1);
  });

  it('replaces with the version that was read', async () => {
    const stub = fetchStub({ body: { ...geofence, version: 2 } });
    const replaced = await api(stub).replaceGeofence(
      geofence.id,
      {
        name: 'Renamed',
        definition: geofence.definition,
        version: 1,
      },
      { tenantId: 'wildlife-dept' },
    );
    expect(stub.last().method).toBe('PUT');
    expect(pathOf(stub.last())).toBe(`/api/geo/v1/geofences/${geofence.id}`);
    expect(stub.last().body).toMatchObject({ version: 1 });
    expect(replaced.version).toBe(2);
  });

  it('archives, purges and makes a delete conditional', async () => {
    const stub = fetchStub({ status: 204 }, { status: 204 });
    await api(stub).deleteGeofence(geofence.id, { tenantId: 'wildlife-dept' });
    expect(parametersOf(stub.last())).toEqual({ tenantId: 'wildlife-dept' });
    await api(stub).deleteGeofence(geofence.id, { purge: true, version: 3 });
    expect(parametersOf(stub.last())).toEqual({ purge: 'true', version: '3' });
  });
});

describe('sites and devices', () => {
  it('reads a device placement as of an instant', async () => {
    const stub = fetchStub({ status: 404, body: { type: 'about:blank', title: 'not found', status: 404 } });
    await api(stub)
      .getDevicePlacement('0199f3d2-0000-0000-0000-000000000001', {
        tenantId: 'wildlife-dept',
        at: '2026-09-01T00:00:00Z',
      })
      .catch(() => undefined);
    expect(pathOf(stub.last())).toBe('/api/geo/v1/devices/0199f3d2-0000-0000-0000-000000000001/placement');
    expect(parametersOf(stub.last())).toEqual({
      tenantId: 'wildlife-dept',
      at: '2026-09-01T00:00:00Z',
    });
  });
});
