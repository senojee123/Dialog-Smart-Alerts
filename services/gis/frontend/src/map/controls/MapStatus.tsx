/**
 * The map's own state, shown on the map: loading, failures, what was cut short, and which reference data
 * release the answers came from.
 *
 * An operator has to be able to tell "there is nothing here" from "this did not load", so a layer that
 * failed is named, with what the service said.
 */
import type { LayerReport } from '../layers/LayerManager';
import { layerById } from '../layers/layerCatalogue';

export interface MapStatusProps {
  readonly reports: Readonly<Record<string, LayerReport>>;
  readonly mapReady: boolean;
  readonly styleFailed: boolean;
  readonly basemapConfigured: boolean;
  readonly interaction: string | null;
}

export function MapStatus({
  reports,
  mapReady,
  styleFailed,
  basemapConfigured,
  interaction,
}: MapStatusProps) {
  const entries = Object.entries(reports);
  const loading = entries.filter(([, report]) => report.status === 'loading');
  const failed = entries.filter(([, report]) => report.status === 'error');
  const truncated = entries.filter(([, report]) => report.truncated);
  const releases = [
    ...new Set(
      entries
        .map(([, report]) => report.refDataRelease)
        .filter((release): release is string => release !== null),
    ),
  ];

  return (
    <div className="map-status" role="status" aria-live="polite">
      {!mapReady && <p className="map-status__line">Loading the map…</p>}
      {styleFailed && (
        <p className="map-status__line map-status__line--error">
          The basemap style could not be loaded; the neutral background is shown instead.
        </p>
      )}
      {mapReady && !basemapConfigured && (
        <p className="map-status__line">
          No basemap configured. Set <code>VITE_BASEMAP_STYLE_URL</code> or <code>VITE_BASEMAPS</code>.
        </p>
      )}
      {interaction !== null && <p className="map-status__line">{interaction}</p>}
      {loading.length > 0 && (
        <p className="map-status__line">Loading {loading.length === 1 ? 'a layer' : `${loading.length} layers`}…</p>
      )}
      {failed.map(([id, report]) => (
        <p key={id} className="map-status__line map-status__line--error">
          {layerById(id)?.title ?? id} did not load: {report.error?.message ?? 'unknown error'}
        </p>
      ))}
      {truncated.length > 0 && (
        <p className="map-status__line map-status__line--warn">
          {truncated.map(([id]) => layerById(id)?.title ?? id).join(', ')}:&nbsp;
          showing the first pages only — zoom in for the rest.
        </p>
      )}
      {releases.length > 0 && (
        <p className="map-status__line map-status__line--quiet">
          Reference data {releases.join(', ')}
        </p>
      )}
    </div>
  );
}
