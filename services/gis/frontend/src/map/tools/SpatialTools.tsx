/**
 * The spatial tools panel: radius search, nearby devices, the ruler and draw-to-filter.
 *
 * The panel is the controls and the answers; `useSpatialTools` holds the state and talks to the API, and
 * the map routes clicks to it while a tool is armed.
 */
import { formatMetres } from '../editor/geofenceDraft';
import type { LayerCatalogue } from '../../types/api';
import {
  MAX_NEAREST_LIMIT,
  MAX_RADIUS_M,
  RADIUS_PRESETS,
  TOOL_HINTS,
  TOOL_LABELS,
  targetsFor,
  totalLengthM,
  type ToolId,
} from './spatialToolModel';
import type { SpatialTools as SpatialToolsState } from './useSpatialTools';

const TOOLS: readonly ToolId[] = ['radius', 'nearby', 'measure', 'filter'];
/** Tools that ask the service nothing. */
const LOCAL_TOOLS: readonly ToolId[] = ['measure', 'filter'];

/** Keep a typed number inside the bounds the API accepts, so it cannot be refused for being out of them. */
function clamp(value: number, lowest: number, highest: number, fallback: number): number {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(highest, Math.max(lowest, Math.round(value)));
}

export interface SpatialToolsProps {
  readonly tools: SpatialToolsState;
  readonly catalogue: LayerCatalogue | null;
  readonly filterActive: boolean;
  readonly onClearFilter: () => void;
  readonly onFocus: (position: readonly [number, number]) => void;
  /**
   * Whether the caller may ask the service spatial questions. Without it, only the tools that work in the
   * browser (measuring, filtering what is drawn) are offered.
   */
  readonly queryTools?: boolean;
}

export function SpatialTools({
  tools,
  catalogue,
  filterActive,
  onClearFilter,
  onFocus,
  queryTools = true,
}: SpatialToolsProps) {
  const targets = targetsFor(catalogue, 'within_distance');
  const offered = queryTools ? TOOLS : LOCAL_TOOLS;

  return (
    <section className="panel" aria-labelledby="spatial-tools-heading">
      <header className="panel__header">
        <h2 id="spatial-tools-heading">Spatial tools</h2>
        {tools.tool !== null && (
          <button
            type="button"
            className="button"
            onClick={() => {
              tools.selectTool(null);
            }}
          >
            Done
          </button>
        )}
      </header>

      <div className="field-row" role="group" aria-label="Tool">
        {offered.map((tool) => (
          <button
            key={tool}
            type="button"
            className={`button ${tools.tool === tool ? 'button--active' : ''}`}
            aria-pressed={tools.tool === tool}
            onClick={() => {
              tools.selectTool(tools.tool === tool ? null : tool);
            }}
          >
            {TOOL_LABELS[tool]}
          </button>
        ))}
      </div>

      {tools.tool !== null && <p className="muted">{TOOL_HINTS[tools.tool]}</p>}

      {tools.tool === 'radius' && (
        <>
          <label className="field">
            <span>Layer to search</span>
            <select
              value={tools.target}
              onChange={(event) => {
                tools.setTarget(event.target.value);
              }}
            >
              {targets.map((layer) => (
                <option key={layer.code} value={layer.code}>
                  {layer.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Distance (m)</span>
            <input
              type="number"
              min={1}
              max={MAX_RADIUS_M}
              step={50}
              value={tools.radiusM}
              onChange={(event) => {
                tools.setRadiusM(clamp(Number(event.target.value), 1, MAX_RADIUS_M, tools.radiusM));
              }}
            />
          </label>
          <div className="field-row">
            {RADIUS_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                className={`button ${tools.radiusM === preset ? 'button--active' : ''}`}
                onClick={() => {
                  tools.setRadiusM(preset);
                }}
              >
                {formatMetres(preset)}
              </button>
            ))}
          </div>
        </>
      )}

      {tools.tool === 'nearby' && (
        <label className="field">
          <span>How many devices</span>
          <input
            type="number"
            min={1}
            max={MAX_NEAREST_LIMIT}
            value={tools.nearestLimit}
            onChange={(event) => {
              tools.setNearestLimit(
                clamp(Number(event.target.value), 1, MAX_NEAREST_LIMIT, tools.nearestLimit),
              );
            }}
          />
        </label>
      )}

      {tools.tool === 'measure' && (
        <div className="measure">
          <p className="measure__total">
            {tools.measure.length < 2
              ? 'Click two or more positions.'
              : `${formatMetres(totalLengthM(tools.measure))} over ${tools.measure.length} positions`}
          </p>
          <div className="field-row">
            <button
              type="button"
              className="button"
              onClick={tools.undoMeasure}
              disabled={tools.measure.length === 0}
            >
              Undo last
            </button>
            <button type="button" className="button" onClick={tools.clearResults}>
              Clear
            </button>
          </div>
          <p className="muted">Distances are metres on the EPSG:5235 plane, as the API measures them.</p>
        </div>
      )}

      {tools.tool === 'filter' && (
        <div className="field-row">
          <button type="button" className="button" onClick={onClearFilter} disabled={!filterActive}>
            Clear filter area
          </button>
        </div>
      )}

      {tools.status === 'running' && <p className="muted">Searching…</p>}
      {tools.stale && (
        <div className="field-row">
          <p className="notice notice--warn" role="status">
            The results below are the previous search.
          </p>
          <button type="button" className="button button--primary" onClick={tools.rerun}>
            Search again
          </button>
        </div>
      )}
      {tools.error !== null && (
        <p className="notice notice--error" role="alert">
          {tools.error}
        </p>
      )}

      {tools.rows.length > 0 && (
        <>
          <h3>
            {tools.rows.length} result{tools.rows.length === 1 ? '' : 's'}
            {tools.truncated && <span className="muted"> (first page)</span>}
          </h3>
          <ul className="results">
            {tools.rows.map((row) => (
              <li key={row.id} className="results__row">
                <button
                  type="button"
                  className="results__name"
                  onClick={() => {
                    if (row.position !== null) {
                      onFocus(row.position);
                    }
                  }}
                  disabled={row.position === null}
                >
                  {row.name}
                </button>
                <span className="results__meta">
                  {row.detail !== null && <span className="muted">{row.detail}</span>}
                  {row.distanceM !== null && <span> {formatMetres(row.distanceM)}</span>}
                  {row.relation !== null && <span className="muted"> {row.relation}</span>}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      {tools.status === 'done' && tools.rows.length === 0 && (
        <p className="muted">Nothing found within the distance searched.</p>
      )}
    </section>
  );
}
