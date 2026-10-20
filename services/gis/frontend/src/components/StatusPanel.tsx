import type { ResourceState } from '../hooks/useApiResource';
import type { CheckStatus, Readiness, ReadinessCheck, ServiceArea } from '../types/api';

const CHECK_LABELS: Readonly<Record<string, string>> = {
  database: 'Database',
  postgis: 'PostGIS',
  spatial_reference_systems: 'Coordinate systems',
  crs_consistency: 'CRS consistency',
  migrations: 'Schema migrations',
};

const STATUS_LABELS: Readonly<Record<CheckStatus, string>> = {
  pass: 'Pass',
  warn: 'Warning',
  fail: 'Fail',
  skip: 'Skipped',
};

function checkSummary(check: ReadinessCheck): string | null {
  const detail = check.detail;
  switch (check.name) {
    case 'database':
      return typeof detail.serverVersion === 'string' ? `PostgreSQL ${detail.serverVersion}` : null;
    case 'postgis':
      return typeof detail.libVersion === 'string' ? `PostGIS ${detail.libVersion}` : null;
    case 'spatial_reference_systems':
      return Array.isArray(detail.required) ? `EPSG ${detail.required.join(', ')}` : null;
    case 'crs_consistency':
      return typeof detail.offsetM === 'number' ? `DB vs app offset ${detail.offsetM} m` : null;
    case 'migrations':
      return Array.isArray(detail.applied) && detail.applied.length > 0
        ? `Revision ${detail.applied.join(', ')}`
        : null;
    default:
      return null;
  }
}

export interface StatusPanelProps {
  readonly readiness: ResourceState<Readiness>;
  readonly serviceArea: ResourceState<ServiceArea>;
  readonly onRefresh: () => void;
}

export function StatusPanel({ readiness, serviceArea, onRefresh }: StatusPanelProps) {
  const report = readiness.data;
  const overall = report === null ? 'unknown' : report.status;

  return (
    <section className="status-panel" aria-labelledby="status-heading">
      <header className="status-panel__header">
        <h2 id="status-heading">Service status</h2>
        <button type="button" className="button" onClick={onRefresh}>
          Refresh
        </button>
      </header>

      <p className={`overall overall--${overall}`} role="status" aria-live="polite">
        {overall === 'ready' && 'Ready'}
        {overall === 'not_ready' && 'Not ready'}
        {overall === 'unknown' && (readiness.status === 'error' ? 'API unreachable' : 'Checking…')}
        {report !== null && <span className="overall__version">v{report.version}</span>}
      </p>

      {readiness.status === 'error' && (
        <p className="notice notice--error">{readiness.error.message}</p>
      )}

      {report !== null && (
        <ul className="checks">
          {report.checks.map((check) => {
            const summary = checkSummary(check);
            return (
              <li key={check.name} className="check">
                <span className={`pill pill--${check.status}`}>{STATUS_LABELS[check.status]}</span>
                <span className="check__body">
                  <span className="check__name">{CHECK_LABELS[check.name] ?? check.name}</span>
                  {summary !== null && <span className="check__summary">{summary}</span>}
                  {check.error !== null && (
                    <span className={check.status === 'skip' ? 'check__summary' : 'check__error'}>
                      {check.error}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <h3>Service area</h3>
      {serviceArea.status === 'success' && (
        <dl className="facts">
          <dt>Bounding box (WGS84)</dt>
          <dd>{serviceArea.data.properties.bbox.map((value) => value.toFixed(2)).join(', ')}</dd>
          <dt>Metric CRS</dt>
          <dd>{serviceArea.data.properties.metricCrs} (SLD99 / Sri Lanka Grid 1999)</dd>
        </dl>
      )}
      {serviceArea.status === 'loading' && <p className="muted">Loading…</p>}
      {serviceArea.status === 'error' && (
        <p className="notice notice--error">{serviceArea.error.message}</p>
      )}
    </section>
  );
}
