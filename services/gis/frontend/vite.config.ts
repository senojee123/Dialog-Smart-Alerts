/// <reference types="vitest/config" />
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

import react from '@vitejs/plugin-react';
import sirv from 'sirv';
import { defineConfig, type Plugin, type ProxyOptions } from 'vite';

// The browser calls the API through /api so no CORS is needed in development.
// GIS_API_PROXY_TARGET points at the FastAPI service (http://api:8000 inside Docker Compose).
const apiProxy: Record<string, ProxyOptions> = {
  '/api': {
    target: process.env.GIS_API_PROXY_TARGET ?? 'http://localhost:8000',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ''),
  },
};

/**
 * Basemaps built by the reference data pipeline (`python -m app.pipeline basemap`), served at /basemap
 * by the dev and preview servers, as the platform's ingress or CDN serves them in production. PMTiles are
 * read with HTTP range requests, which sirv answers. GIS_BASEMAP_DIR is where they are (../data/basemap
 * by default; Docker Compose mounts it).
 */
function basemapFiles(): Plugin {
  const directory = resolve(process.env.GIS_BASEMAP_DIR ?? '../data/basemap');
  const serve = sirv(directory, {
    dev: true,
    etag: true,
    // A missing file is a 404, not the application's index page.
    onNoMatch: (_request, response) => {
      response.statusCode = 404;
      response.end();
    },
  });
  const mount = (server: { middlewares: { use: (path: string, handler: typeof serve) => unknown } }) => {
    if (existsSync(directory)) {
      // Without `next`, sirv answers a missing file itself instead of passing it on.
      server.middlewares.use('/basemap', (request, response) => {
        serve(request, response);
      });
    }
  };
  return { name: 'gis-basemap-files', configureServer: mount, configurePreviewServer: mount };
}

// Docker Desktop on Windows/macOS does not forward file-change events into containers.
const usePolling = process.env.VITE_USE_POLLING === 'true';

export default defineConfig({
  // Where the built application is served. The main platform serves it at /gis-app/ (GIS_WEB_BASE,
  // set by the platform image's build); the dev server and the standalone build use the root.
  base: process.env.GIS_WEB_BASE ?? '/',
  plugins: [react(), basemapFiles()],
  // The map needs no PostCSS. An inline (empty) configuration stops Vite searching parent folders, where
  // the main platform's repository keeps its own (Tailwind) postcss.config.js.
  css: { postcss: {} },
  server: {
    port: 5173,
    strictPort: true,
    proxy: apiProxy,
    watch: usePolling ? { usePolling: true, interval: 300 } : undefined,
  },
  preview: {
    port: 4173,
    proxy: apiProxy,
  },
  build: {
    target: 'es2022',
    sourcemap: true,
    // MapLibre GL JS alone is ~1 MB minified (1.1 MB with pmtiles and react-map-gl). Keep it in its own
    // long-cached chunk so application releases do not force field devices on 4G to download it again.
    chunkSizeWarningLimit: 1200,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'maplibre', test: /node_modules[\\/](maplibre-gl|pmtiles|react-map-gl|@vis\.gl)[\\/]/ },
            // Terra Draw is only needed once the operator draws something, and it changes on its own
            // release cycle, so it is worth its own long-cached chunk.
            { name: 'draw', test: /node_modules[\\/]terra-draw/ },
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
          ],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
