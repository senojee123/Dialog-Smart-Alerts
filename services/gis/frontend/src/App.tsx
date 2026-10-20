/**
 * The reference application around the map.
 *
 * This is a thin shell: a header, the service's own status, and `MapContainer`. The map is the product -
 * the shell exists so it can be run and looked at, and so the component it embeds is the same one an
 * investigation or control-room application would embed (see `docs/frontend/map-client.md`).
 *
 * Inside the main platform's page (a frame) the header is left out - the platform has its own
 * (`embedding.ts`).
 */
import { useCallback, useState } from 'react';

import { StatusPanel } from './components/StatusPanel';
import { config } from './config';
import { isEmbedded } from './embedding';
import { useApiResource } from './hooks/useApiResource';
import { MapContainer } from './map/MapContainer';
import { parseViewHash } from './map/mapStyle';
import type { Selection } from './map/state/mapState';
import { gisApi } from './services/gisApi';

export function App() {
  const loadReadiness = useCallback((signal: AbortSignal) => gisApi.getReadiness({ signal }), []);
  const loadServiceArea = useCallback((signal: AbortSignal) => gisApi.getServiceArea({ signal }), []);
  const readiness = useApiResource(loadReadiness, { pollIntervalMs: config.healthPollIntervalMs });
  const serviceArea = useApiResource(loadServiceArea);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [statusOpen, setStatusOpen] = useState(false);
  // A linked view (`#map=<zoom>/<lat>/<lon>`) is read once, when the application opens.
  const [initialView] = useState(() => parseViewHash(window.location.hash));
  const [embedded] = useState(() => isEmbedded());

  return (
    <div className={embedded ? 'app app--embedded' : 'app'}>
      {!embedded && (
        <header className="app__header">
          <h1>GIS Core Service</h1>
          <p className="app__subtitle">Geospatial intelligence · Sri Lanka</p>
          <span className="app__spacer" />
          {selection !== null && (
            <p className="app__selection">
              Selected: {selection.layerId} · {selection.featureId.slice(0, 8)}
            </p>
          )}
          <button
            type="button"
            className="button button--header"
            onClick={() => {
              setStatusOpen((open) => !open);
            }}
            aria-expanded={statusOpen}
          >
            {readiness.data?.status === 'ready' ? 'Service ready' : 'Service status'}
          </button>
        </header>
      )}

      <main className="app__main">
        <MapContainer api={gisApi} initialView={initialView} onSelectionChange={setSelection} />
        {statusOpen && (
          <aside className="app__status">
            <StatusPanel readiness={readiness} serviceArea={serviceArea} onRefresh={readiness.refresh} />
          </aside>
        )}
      </main>
    </div>
  );
}
