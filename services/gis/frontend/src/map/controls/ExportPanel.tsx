/**
 * Exports: the features of one layer in the current view, or the events of the current window, as a
 * GeoJSON file.
 *
 * Offered only to callers with the export permission. An export is the whole selection or nothing - the
 * service refuses one that is too large rather than cutting it short - and every export is recorded in the
 * service's audit log, which the panel says, so nobody is surprised to find it there.
 */
import { useState } from 'react';

import type { Bounds } from '../../geo/geometry';
import { ApiError } from '../../services/apiClient';
import type { EventExportQuery, GisApi } from '../../services/gisApi';
import type { MapLayerDefinition } from '../layers/layerCatalogue';
import { exportFilename, saveGeoJson, type SaveFile } from './download';

export interface ExportPanelProps {
  readonly api: GisApi;
  readonly tenantId: string | null;
  /**
   * Layers that can be exported: those with a code in the service's catalogue whose sources allow
   * redistribution (the service refuses the others).
   */
  readonly layers: readonly MapLayerDefinition[];
  /** The area to export: the view the operator is looking at. */
  readonly bounds: Bounds | null;
  /** The event selection to export, resolved when asked for; `null` when events cannot be exported. */
  readonly events: (() => EventExportQuery) | null;
  readonly save?: SaveFile;
}

type Outcome =
  | { readonly kind: 'idle' }
  | { readonly kind: 'busy'; readonly what: string }
  | {
      readonly kind: 'done';
      readonly what: string;
      readonly count: number;
      readonly attribution: readonly string[];
    }
  | { readonly kind: 'failed'; readonly message: string };

function failure(error: unknown): string {
  if (error instanceof ApiError) {
    return error.problem?.detail ?? error.summary;
  }
  return error instanceof Error ? error.message : String(error);
}

export function ExportPanel({
  api,
  tenantId,
  layers,
  bounds,
  events,
  save = saveGeoJson,
}: ExportPanelProps) {
  const exportable = layers.filter((layer) => layer.apiLayer !== null);
  const [layerId, setLayerId] = useState<string>(exportable[0]?.id ?? '');
  const [outcome, setOutcome] = useState<Outcome>({ kind: 'idle' });
  const chosen = exportable.find((layer) => layer.id === layerId) ?? exportable[0];
  const busy = outcome.kind === 'busy';

  const exportLayer = async (layer: MapLayerDefinition, code: string) => {
    setOutcome({ kind: 'busy', what: layer.title });
    try {
      const document = await api.exportFeatures({ layer: code, bounds, tenantId });
      save(document, exportFilename(code, document.exportedAt));
      setOutcome({
        kind: 'done',
        what: layer.title,
        count: document.count,
        attribution: document.attribution,
      });
    } catch (error) {
      setOutcome({ kind: 'failed', message: failure(error) });
    }
  };

  const exportEvents = async (selection: EventExportQuery) => {
    setOutcome({ kind: 'busy', what: 'Events' });
    try {
      const document = await api.exportEvents(selection);
      save(document, exportFilename('events', document.exportedAt));
      setOutcome({ kind: 'done', what: 'Events', count: document.count, attribution: document.attribution });
    } catch (error) {
      setOutcome({ kind: 'failed', message: failure(error) });
    }
  };

  return (
    <section className="panel" aria-labelledby="export-heading">
      <header className="panel__header">
        <h2 id="export-heading">Export</h2>
      </header>

      {chosen !== undefined && (
        <div className="field-row">
          <label className="field">
            <span>Layer</span>
            <select
              value={chosen.id}
              onChange={(event) => {
                setLayerId(event.target.value);
              }}
            >
              {exportable.map((layer) => (
                <option key={layer.id} value={layer.id}>
                  {layer.title}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="button"
            disabled={busy || bounds === null}
            onClick={() => {
              if (chosen.apiLayer !== null) {
                void exportLayer(chosen, chosen.apiLayer);
              }
            }}
          >
            Export view
          </button>
        </div>
      )}

      {events !== null && (
        <button
          type="button"
          className="button"
          disabled={busy}
          onClick={() => {
            void exportEvents(events());
          }}
        >
          Export events of the window
        </button>
      )}

      {outcome.kind === 'busy' && <p className="muted">Exporting {outcome.what}…</p>}
      {outcome.kind === 'done' && (
        <p className="muted" role="status">
          {outcome.what}: {outcome.count} features exported.
          {outcome.attribution.length > 0 && (
            <> Keep the attribution with the data: {outcome.attribution.join('; ')}.</>
          )}
        </p>
      )}
      {outcome.kind === 'failed' && (
        <p className="notice notice--error" role="alert">
          {outcome.message}
        </p>
      )}
      <p className="muted">Exports are recorded in the service&apos;s audit log.</p>
    </section>
  );
}
