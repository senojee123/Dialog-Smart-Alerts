/**
 * The map client end to end, in Chromium, against a running API with the development sample loaded.
 *
 * 1. An event submitted to `POST /geo/v1/enrich` appears on the MapLibre map, can be selected, and its
 *    popup shows the geographic context the service resolved.
 * 2. A circle geofence drawn with the editor is stored by the service, and an event inside it hits it.
 * 3. After switching the basemap, a polygon geofence can still be drawn; a corner dragged while it is
 *    selected is kept when it is deselected, and the service stores the polygon as edited.
 *
 * Positions are in the pilot area, away from the sample's own events, so nothing else is drawn there.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8100';
const TENANT = process.env.E2E_TENANT ?? 'wildlife-dept';
// Above the zoom where events are clustered (clusterMaxZoom 15), so one event is one symbol.
const EVENT_ZOOM = 16.5;
const DRAW_ZOOM = 15;

interface GeoContext {
  readonly eventId: string;
  readonly refDataRelease: string;
  readonly admin: { readonly codes: Readonly<Record<string, string | null>> };
  readonly nearestSettlement: { readonly name: string } | null;
  readonly nearestRoad: { readonly distanceM: number } | null;
  readonly geofenceHits: readonly { readonly id: string; readonly name: string }[];
}

interface StoredGeofence {
  readonly id: string;
  readonly definition: {
    readonly kind: string;
    readonly radiusM: number | null;
    readonly geometry: { readonly type: string; readonly coordinates: unknown };
  };
}

/** A run's own mark, so nothing from an earlier run can stand in for what this one created. */
function runMark(): string {
  return Date.now().toString(36);
}

/** Requests act for the tenant in this header; the GIS checks no credentials (the platform owns sign-in). */
function asTenant(): Record<string, string> {
  return { 'X-GIS-Tenant-Id': TENANT };
}

async function enrich(
  request: APIRequestContext,
  eventId: string,
  longitude: number,
  latitude: number,
  eventType: string,
): Promise<GeoContext> {
  const response = await request.post(`${API}/geo/v1/enrich`, {
    headers: asTenant(),
    data: {
      eventId,
      tenantId: TENANT,
      observedAt: new Date().toISOString(),
      eventType,
      sourceType: 'external',
      locationSource: 'external',
      location: { type: 'Point', coordinates: [longitude, latitude] },
      locationAccuracyM: 10,
      metadata: { e2e: true },
    },
  });
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as GeoContext;
}

/**
 * Collects the page's uncaught errors. Some failures never reach the DOM - Terra Draw rendering into a
 * source a new map style removed fails in an animation frame - so every test ends by asserting none.
 */
function watchErrors(page: Page): readonly string[] {
  const errors: string[] = [];
  page.on('pageerror', (error) => {
    errors.push(error.message);
  });
  return errors;
}

/** Opens the map at a view and waits until the service has answered for it. */
async function openAt(
  page: Page,
  longitude: number,
  latitude: number,
  zoom: number,
): Promise<{ x: number; y: number }> {
  await page.goto(`/#map=${zoom}/${latitude}/${longitude}`);
  await expect(page.getByRole('button', { name: 'Service ready' })).toBeVisible({ timeout: 30_000 });
  const canvas = page.locator('canvas.maplibregl-canvas');
  await expect(canvas).toBeVisible();
  const box = await canvas.boundingBox();
  if (box === null) {
    throw new Error('the map canvas has no box');
  }
  // The view is centred on the position asked for.
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/** The one geofence of the tenant with this name, as the service stored it. */
async function storedGeofence(request: APIRequestContext, name: string): Promise<StoredGeofence> {
  const listed = await request.get(`${API}/geo/v1/geofences`, {
    headers: asTenant(),
    params: { tenantId: TENANT, nameContains: name },
  });
  expect(listed.status()).toBe(200);
  const { items } = (await listed.json()) as { items: StoredGeofence[] };
  expect(items).toHaveLength(1);
  const [fence] = items;
  if (fence === undefined) {
    throw new Error('the geofence was not stored');
  }
  return fence;
}

/** Leaves the tenant as it was: the geofence is archived. */
async function archive(request: APIRequestContext, geofenceId: string): Promise<void> {
  const archived = await request.delete(`${API}/geo/v1/geofences/${geofenceId}`, {
    headers: asTenant(),
    params: { tenantId: TENANT },
  });
  expect(archived.ok()).toBe(true);
}

test('an event submitted to the API appears on the map with its geographic context', async ({
  page,
  request,
}) => {
  const errors = watchErrors(page);
  // A different spot on each run, so earlier runs' events are not drawn on top of this one, and an
  // event id and type of this run only, so the event selected is the one this run submitted.
  const mark = runMark();
  const offset = (Date.now() % 997) * 1e-5;
  const [longitude, latitude] = [80.8 + offset, 8.09];
  const eventId = `${mark}-e2e-map`;
  const eventType = `test.e2e_map_${mark}`;
  const context = await enrich(request, eventId, longitude, latitude, eventType);
  expect(context.refDataRelease).toMatch(/^ref-/);
  expect(context.admin.codes.l1).not.toBeNull();
  expect(context.nearestSettlement).not.toBeNull();
  expect(context.nearestRoad).not.toBeNull();

  const centre = await openAt(page, longitude, latitude, EVENT_ZOOM);
  const popup = page.locator('.maplibregl-popup');
  // The event layer loads after the map has settled; click the event until it is drawn and selected
  // (a click before that selects the area underneath, whose popup is closed before trying again).
  await expect(async () => {
    const close = page.locator('.maplibregl-popup-close-button');
    if ((await close.count()) > 0) {
      await close.first().click();
    }
    await page.mouse.click(centre.x, centre.y);
    await expect(popup).toContainText(eventType, { timeout: 2_000 });
  }).toPass({ timeout: 60_000 });
  await expect(page.getByText(`Selected: events · ${eventId.slice(0, 8)}`)).toBeVisible();
  // The popup resolves the event's geographic context from the service: the administrative areas, the
  // nearest settlement and road, and the release they come from.
  await expect(popup).toContainText('Province');
  await expect(popup).toContainText('Nearest settlement');
  await expect(popup).toContainText(context.nearestSettlement?.name ?? '');
  await expect(popup).toContainText('Nearest road');
  await expect(popup).toContainText(context.refDataRelease);
  await page.screenshot({ path: 'test-results/event-on-map.png' });
  expect(errors).toEqual([]);
});

test('a geofence drawn with the editor is stored, and an event inside it hits it', async ({
  page,
  request,
}) => {
  const errors = watchErrors(page);
  const [longitude, latitude] = [80.83, 8.1];
  const name = `E2E drawn circle ${runMark()}`;
  const centre = await openAt(page, longitude, latitude, DRAW_ZOOM);

  await page.getByRole('button', { name: 'New geofence' }).click();
  const circle = page.getByRole('button', { name: 'Circle', exact: true });
  await expect(circle).toBeEnabled({ timeout: 30_000 });
  await circle.click();
  // Click the centre, then click again at the radius: 80 px is about 190 m at zoom 15 here.
  await page.mouse.click(centre.x, centre.y);
  await page.mouse.move(centre.x + 80, centre.y, { steps: 12 });
  await page.mouse.click(centre.x + 80, centre.y);
  await page.getByLabel('Name').fill(name);
  await page.getByRole('button', { name: 'Create geofence' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved as version 1' })).toBeVisible({
    timeout: 15_000,
  });

  const fence = await storedGeofence(request, name);
  try {
    expect(fence.definition.kind).toBe('circle');
    expect(fence.definition.radiusM).toBeGreaterThan(150);
    expect(fence.definition.radiusM).toBeLessThan(240);
    const [fenceLongitude, fenceLatitude] = fence.definition.geometry.coordinates as number[];
    expect(fenceLongitude).toBeCloseTo(longitude, 3);
    expect(fenceLatitude).toBeCloseTo(latitude, 3);

    const context = await enrich(request, `${runMark()}-e2e-fence`, longitude, latitude, 'test.e2e_fence_check');
    expect(context.geofenceHits.map((hit) => hit.id)).toContain(fence.id);
    await page.screenshot({ path: 'test-results/geofence-drawn.png' });
  } finally {
    await archive(request, fence.id);
  }
  expect(errors).toEqual([]);
});

test('after a basemap switch, a polygon is drawn, edited and deselected, and stored as edited', async ({
  page,
  request,
}) => {
  const errors = watchErrors(page);
  const [longitude, latitude] = [80.86, 8.12];
  const name = `E2E drawn polygon ${runMark()}`;
  const centre = await openAt(page, longitude, latitude, DRAW_ZOOM);

  // Replacing the map's style takes Terra Draw's layers with it; drawing must still work afterwards.
  // The editor's shapes are offered once Terra Draw has started on the loaded map, so the switch waits
  // for that: switching earlier would only give Terra Draw the new style to start on.
  await page.getByRole('button', { name: 'New geofence' }).click();
  const polygon = page.getByRole('button', { name: 'Polygon', exact: true });
  await expect(polygon).toBeEnabled({ timeout: 30_000 });
  await page.getByLabel('Basemap').selectOption('neutral');
  await expect(polygon).toBeEnabled({ timeout: 30_000 });
  await polygon.click();
  const corners = [
    [centre.x - 60, centre.y - 60],
    [centre.x + 60, centre.y - 60],
    [centre.x + 60, centre.y + 60],
    [centre.x - 60, centre.y + 60],
  ] as const;
  for (const [x, y] of corners) {
    await page.mouse.move(x, y, { steps: 6 });
    await page.mouse.click(x, y);
  }
  // Clicking the first corner again closes the polygon; the editor then selects it for editing.
  await page.mouse.move(corners[0][0], corners[0][1], { steps: 6 });
  await page.mouse.click(corners[0][0], corners[0][1]);
  await page.getByLabel('Name').fill(name);
  const create = page.getByRole('button', { name: 'Create geofence' });
  await expect(create).toBeEnabled();
  // Select it, drag its south-east corner 40 px further out, and deselect it with a click on the empty
  // map: Terra Draw removes the corner handles it added, and the draft must keep the edited shape.
  await page.mouse.click(centre.x - 20, centre.y + 20);
  await page.mouse.move(centre.x + 60, centre.y + 60, { steps: 6 });
  await page.mouse.down();
  await page.mouse.move(centre.x + 100, centre.y + 100, { steps: 10 });
  await page.mouse.up();
  await page.mouse.click(centre.x + 250, centre.y + 180);
  await expect(page.getByText('Draw the geofence on the map.')).toHaveCount(0);
  await expect(create).toBeEnabled();
  await create.click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved as version 1' })).toBeVisible({
    timeout: 15_000,
  });

  const fence = await storedGeofence(request, name);
  try {
    expect(fence.definition.kind).toBe('polygon');
    const [ring] = fence.definition.geometry.coordinates as [number, number][][];
    if (ring === undefined) {
      throw new Error('the polygon has no ring');
    }
    // Four corners and the closing position ...
    expect(ring).toHaveLength(5);
    // ... one of them where it was dragged to: at zoom 15 a pixel is 360 / (512 * 2^15) = 0.0000215
    // degrees, so the dragged corner is 0.0021 degrees east of the centre and the others 0.0013.
    const east = Math.max(...ring.map(([x]) => x)) - longitude;
    expect(east).toBeGreaterThan(0.0018);
    expect(east).toBeLessThan(0.0025);
    const context = await enrich(request, `${runMark()}-e2e-polygon`, longitude, latitude, 'test.e2e_fence_check');
    expect(context.geofenceHits.map((hit) => hit.id)).toContain(fence.id);
    await page.screenshot({ path: 'test-results/polygon-drawn.png' });
  } finally {
    await archive(request, fence.id);
  }
  expect(errors).toEqual([]);
});
