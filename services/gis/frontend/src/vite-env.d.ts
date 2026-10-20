/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the GIS API. Defaults to `/api`, which the dev server proxies to FastAPI. */
  readonly VITE_API_BASE_URL?: string;
  /** Optional MapLibre style URL for the basemap. */
  readonly VITE_BASEMAP_STYLE_URL?: string;
  /** How often the status panel re-checks readiness, in milliseconds. */
  readonly VITE_HEALTH_POLL_INTERVAL_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
