/**
 * Runtime configuration, resolved once from Vite environment variables (`VITE_*`).
 *
 * Nothing here is a secret. The GIS runs as an instance of the main platform, which owns users and
 * sign-in, so the map sends no credentials (see `docs/frontend/map-client.md`).
 */
import { z } from 'zod';

/** A selectable basemap. `styleUrl` of `null` is the built-in neutral background. */
export interface Basemap {
  readonly id: string;
  readonly label: string;
  readonly styleUrl: string | null;
}

export interface AppConfig {
  /** Base URL for API calls, without a trailing slash. */
  readonly apiBaseUrl: string;
  /** Basemaps the operator can switch between; always at least the neutral background. */
  readonly basemaps: readonly Basemap[];
  /** Id of the basemap to show first. */
  readonly defaultBasemapId: string;
  /** Readiness polling interval in milliseconds. */
  readonly healthPollIntervalMs: number;
  /** Tenant whose operational data to read; `null`: the platform's organisation (`GIS_TENANT_ID`). */
  readonly tenantId: string | null;
  /** Features to request per page. */
  readonly featureLimit: number;
  /** Pages to follow per layer per viewport, so a wide view cannot page forever. */
  readonly maxFeaturePages: number;
  /** Width of the event time window in hours when the operator has not chosen one. */
  readonly eventWindowHours: number;
  /** Re-read events on this interval in milliseconds; `0` leaves refreshing to the operator. */
  readonly eventRefreshIntervalMs: number;
}

export interface RawEnv {
  /** Set by Vite: true in a production build. */
  readonly PROD?: boolean | undefined;
  readonly VITE_API_BASE_URL?: string | undefined;
  readonly VITE_BASEMAP_STYLE_URL?: string | undefined;
  readonly VITE_BASEMAPS?: string | undefined;
  readonly VITE_HEALTH_POLL_INTERVAL_MS?: string | undefined;
  readonly VITE_TENANT_ID?: string | undefined;
  readonly VITE_FEATURE_LIMIT?: string | undefined;
  readonly VITE_MAX_FEATURE_PAGES?: string | undefined;
  readonly VITE_EVENT_WINDOW_HOURS?: string | undefined;
  readonly VITE_EVENT_REFRESH_INTERVAL_MS?: string | undefined;
}

const DEFAULT_POLL_INTERVAL_MS = 15_000;
const MIN_POLL_INTERVAL_MS = 2_000;
const DEFAULT_FEATURE_LIMIT = 500;
const MAX_FEATURE_LIMIT = 1_000;
const DEFAULT_MAX_FEATURE_PAGES = 4;
const DEFAULT_EVENT_WINDOW_HOURS = 24;
/** `GET /geo/v1/events` refuses a window longer than 31 days. */
const MAX_EVENT_WINDOW_HOURS = 31 * 24;

export const NEUTRAL_BASEMAP: Basemap = { id: 'neutral', label: 'No basemap', styleUrl: null };

// A style URL: absolute, or a path on this site (`/basemap/...`), as VITE_BASEMAP_STYLE_URL accepts.
const styleUrlSchema = z.union([z.url(), z.string().regex(/^\/[^/\s]\S*$/)]);

const basemapListSchema = z.array(
  z.object({ id: z.string().min(1).max(50), label: z.string().min(1).max(80), styleUrl: styleUrlSchema }),
);

function number(raw: string | undefined, fallback: number, minimum: number, maximum: number): number {
  const trimmed = raw?.trim() ?? '';
  const value = Number(trimmed);
  if (trimmed === '' || !Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(maximum, Math.max(minimum, Math.trunc(value)));
}

function text(raw: string | undefined): string | null {
  const value = raw?.trim() ?? '';
  return value === '' ? null : value;
}

/**
 * The basemaps: `VITE_BASEMAPS` (a JSON array) when it parses, otherwise the single
 * `VITE_BASEMAP_STYLE_URL`, and the neutral background either way so the map always has a style.
 */
export function resolveBasemaps(env: RawEnv): readonly Basemap[] {
  const raw = text(env.VITE_BASEMAPS);
  if (raw !== null) {
    const parsed = basemapListSchema.safeParse(parseJson(raw));
    if (parsed.success && parsed.data.length > 0) {
      return [...parsed.data, NEUTRAL_BASEMAP];
    }
    // A malformed list is a deployment mistake, not a reason to render nothing.
    console.warn('VITE_BASEMAPS is not a valid basemap list; falling back to VITE_BASEMAP_STYLE_URL');
  }
  const single = text(env.VITE_BASEMAP_STYLE_URL);
  return single === null
    ? [NEUTRAL_BASEMAP]
    : [{ id: 'basemap', label: 'Basemap', styleUrl: single }, NEUTRAL_BASEMAP];
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

export function resolveConfig(env: RawEnv): AppConfig {
  const apiBaseUrl = text(env.VITE_API_BASE_URL) ?? '/api';
  const basemaps = resolveBasemaps(env);
  return {
    apiBaseUrl: apiBaseUrl.replace(/\/+$/, ''),
    basemaps,
    defaultBasemapId: basemaps[0]?.id ?? NEUTRAL_BASEMAP.id,
    healthPollIntervalMs: number(
      env.VITE_HEALTH_POLL_INTERVAL_MS,
      DEFAULT_POLL_INTERVAL_MS,
      MIN_POLL_INTERVAL_MS,
      3_600_000,
    ),
    tenantId: text(env.VITE_TENANT_ID),
    featureLimit: number(env.VITE_FEATURE_LIMIT, DEFAULT_FEATURE_LIMIT, 1, MAX_FEATURE_LIMIT),
    maxFeaturePages: number(env.VITE_MAX_FEATURE_PAGES, DEFAULT_MAX_FEATURE_PAGES, 1, 50),
    eventWindowHours: number(
      env.VITE_EVENT_WINDOW_HOURS,
      DEFAULT_EVENT_WINDOW_HOURS,
      1,
      MAX_EVENT_WINDOW_HOURS,
    ),
    eventRefreshIntervalMs: number(env.VITE_EVENT_REFRESH_INTERVAL_MS, 0, 0, 3_600_000),
  };
}

export const config: AppConfig = resolveConfig(import.meta.env);
