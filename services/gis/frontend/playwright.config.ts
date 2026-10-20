/**
 * Browser end-to-end tests (`npm run e2e`): the map client in Chromium against a running API.
 *
 *   E2E_TENANT     the tenant (default wildlife-dept: load it with setup -WithSampleTenant)
 *   E2E_API_URL    the API (default http://127.0.0.1:8100)
 *   E2E_BASE_URL   an already running map client; without it a dev server is started on port 5175,
 *                  proxying /api to E2E_API_URL and reading E2E_TENANT
 *   E2E_CHROMIUM_PATH  a Chromium to use instead of Playwright's own (`npx playwright install chromium`)
 *
 * The API needs reference data (the development sample). No credentials: the main platform owns sign-in.
 */
import { defineConfig } from '@playwright/test';

const apiUrl = process.env.E2E_API_URL ?? 'http://127.0.0.1:8100';
const external = process.env.E2E_BASE_URL;
const baseURL = external ?? 'http://127.0.0.1:5175';
const chromium = process.env.E2E_CHROMIUM_PATH;

export default defineConfig({
  testDir: 'e2e',
  testMatch: '**/*.e2e.ts',
  timeout: 120_000,
  workers: 1,
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    baseURL,
    viewport: { width: 1400, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: {
      // WebGL2 in software, so the tests also run on machines without a GPU (CI, containers).
      args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
      ...(chromium === undefined ? {} : { executablePath: chromium }),
    },
  },
  ...(external === undefined
    ? {
        webServer: {
          command: 'npm run dev -- --port 5175 --strictPort --host 127.0.0.1',
          url: baseURL,
          reuseExistingServer: false,
          timeout: 60_000,
          env: {
            GIS_API_PROXY_TARGET: apiUrl,
            VITE_TENANT_ID: process.env.E2E_TENANT ?? 'wildlife-dept',
            VITE_BASEMAP_STYLE_URL: process.env.VITE_BASEMAP_STYLE_URL ?? '/basemap/ref-2026.09-dev/style.json',
          },
        },
      }
    : {}),
});
