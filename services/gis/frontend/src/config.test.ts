import { describe, expect, it, vi } from 'vitest';

import { NEUTRAL_BASEMAP, resolveBasemaps, resolveConfig } from './config';

describe('resolveConfig', () => {
  it('falls back to the proxy path and the neutral basemap', () => {
    const config = resolveConfig({});
    expect(config.apiBaseUrl).toBe('/api');
    expect(config.basemaps).toEqual([NEUTRAL_BASEMAP]);
    expect(config.defaultBasemapId).toBe(NEUTRAL_BASEMAP.id);
    expect(config.tenantId).toBeNull();
    expect(config).not.toHaveProperty('accessToken');
  });

  it('trims the base URL and drops trailing slashes', () => {
    expect(resolveConfig({ VITE_API_BASE_URL: ' https://gis.example/api// ' }).apiBaseUrl).toBe(
      'https://gis.example/api',
    );
  });

  it('keeps the defaults when a number is absent or not a number', () => {
    const config = resolveConfig({ VITE_FEATURE_LIMIT: 'lots' });
    expect(config.featureLimit).toBe(500);
    expect(config.maxFeaturePages).toBe(4);
    expect(config.eventWindowHours).toBe(24);
    expect(config.eventRefreshIntervalMs).toBe(0);
    expect(config.healthPollIntervalMs).toBe(15_000);
  });

  it('clamps the numbers it is given', () => {
    const config = resolveConfig({
      VITE_FEATURE_LIMIT: '99999',
      VITE_MAX_FEATURE_PAGES: '0',
      VITE_EVENT_WINDOW_HOURS: '10000',
      VITE_HEALTH_POLL_INTERVAL_MS: '10',
    });
    expect(config.featureLimit).toBe(1000);
    expect(config.maxFeaturePages).toBe(1);
    expect(config.eventWindowHours).toBe(31 * 24);
    expect(config.healthPollIntervalMs).toBe(2_000);
  });

  it('reads the tenant', () => {
    expect(resolveConfig({ VITE_TENANT_ID: ' wildlife-dept ' }).tenantId).toBe('wildlife-dept');
  });
});

describe('resolveBasemaps', () => {
  it('accepts style paths on the same site in a basemap list', () => {
    const basemaps = resolveBasemaps({
      VITE_BASEMAPS: JSON.stringify([
        { id: 'basemap', label: 'Sri Lanka (offline)', styleUrl: '/basemap/ref-2026.09-dev/style.json' },
        { id: 'osm', label: 'OpenStreetMap (online)', styleUrl: '/gis-app/basemaps/osm-standard.json' },
      ]),
    });
    expect(basemaps.map((basemap) => basemap.id)).toEqual(['basemap', 'osm', NEUTRAL_BASEMAP.id]);
  });

  it('refuses a protocol-relative or blank style path', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    for (const styleUrl of ['//evil.example/style.json', '/', 'basemap/style.json']) {
      expect(resolveBasemaps({ VITE_BASEMAPS: JSON.stringify([{ id: 'x', label: 'X', styleUrl }]) })).toEqual([
        NEUTRAL_BASEMAP,
      ]);
    }
    warn.mockRestore();
  });

  it('turns a single style URL into a basemap, with the neutral one beside it', () => {
    const basemaps = resolveBasemaps({ VITE_BASEMAP_STYLE_URL: 'https://tiles.example/style.json' });
    expect(basemaps).toHaveLength(2);
    expect(basemaps[0]?.styleUrl).toBe('https://tiles.example/style.json');
    expect(basemaps[1]).toEqual(NEUTRAL_BASEMAP);
  });

  it('reads a list of basemaps', () => {
    const basemaps = resolveBasemaps({
      VITE_BASEMAPS: JSON.stringify([
        { id: 'osm', label: 'OpenStreetMap', styleUrl: 'https://tiles.example/osm.json' },
        { id: 'sat', label: 'Satellite', styleUrl: 'https://tiles.example/sat.json' },
      ]),
    });
    expect(basemaps.map((basemap) => basemap.id)).toEqual(['osm', 'sat', NEUTRAL_BASEMAP.id]);
  });

  it('falls back to the single style when the list is malformed, and says so', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const basemaps = resolveBasemaps({
      VITE_BASEMAPS: '[{"id": "broken"}]',
      VITE_BASEMAP_STYLE_URL: 'https://tiles.example/style.json',
    });
    expect(basemaps[0]?.id).toBe('basemap');
    expect(warn).toHaveBeenCalled();
  });

  it('refuses a style that is not a URL', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(
      resolveBasemaps({ VITE_BASEMAPS: '[{"id":"a","label":"A","styleUrl":"not a url"}]' }),
    ).toEqual([NEUTRAL_BASEMAP]);
    expect(warn).toHaveBeenCalled();
  });
});
