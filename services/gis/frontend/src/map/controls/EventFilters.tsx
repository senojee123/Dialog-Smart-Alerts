/**
 * Event filters: type, source and time.
 *
 * The window is bounded because the service bounds it - event storage is partitioned by month, and a
 * window longer than 31 days is refused rather than made to scan every partition. The panel shows the
 * window the service answered for, not the one that was asked for, so an operator is never looking at a
 * different span than they think.
 */
import { fromLocalInput, toLocalInput } from '../editor/localTime';
import { formatInstant } from '../popup/featureSummary';
import {
  MAX_EVENT_WINDOW_DAYS,
  WINDOW_PRESETS,
  windowIsTooLong,
  type EventFilterState,
  type TimeWindow,
} from '../state/mapState';

export interface EventFiltersProps {
  readonly filters: EventFilterState;
  readonly onChange: (filters: EventFilterState) => void;
  /** Event types seen in the loads so far, offered as the choices of the type filter. */
  readonly knownEventTypes: readonly string[];
  readonly knownSourceTypes: readonly string[];
  readonly answeredWindow: TimeWindow | null;
  readonly count: number;
  readonly truncated: boolean;
  readonly loadedAt: Date | null;
  readonly onRefresh: () => void;
  readonly disabled: boolean;
}

export function EventFilters({
  filters,
  onChange,
  knownEventTypes,
  knownSourceTypes,
  answeredWindow,
  count,
  truncated,
  loadedAt,
  onRefresh,
  disabled,
}: EventFiltersProps) {
  // The type in force is always an option, even when a host set it before any event of it was loaded.
  const eventTypeOptions =
    filters.eventType !== null && !knownEventTypes.includes(filters.eventType)
      ? [...knownEventTypes, filters.eventType].sort((a, b) => a.localeCompare(b))
      : knownEventTypes;
  const pinned = filters.from !== null || filters.to !== null;
  const tooLong =
    filters.from !== null && filters.to !== null && windowIsTooLong({ from: filters.from, to: filters.to });

  return (
    <section className="panel" aria-labelledby="events-heading">
      <header className="panel__header">
        <h2 id="events-heading">Event filters</h2>
        <button type="button" className="button" onClick={onRefresh} disabled={disabled}>
          Reload
        </button>
      </header>

      {disabled && <p className="muted">Turn the event layer on to load events.</p>}

      <div className="field-row" role="group" aria-label="Time window">
        {WINDOW_PRESETS.map((preset) => (
          <button
            key={preset.hours}
            type="button"
            className={`button ${!pinned && filters.windowHours === preset.hours ? 'button--active' : ''}`}
            onClick={() => {
              onChange({ ...filters, windowHours: preset.hours, from: null, to: null });
            }}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="field-row">
        <label className="field">
          <span>From</span>
          <input
            type="datetime-local"
            value={toLocalInput(filters.from)}
            onChange={(event) => {
              onChange({ ...filters, from: fromLocalInput(event.target.value) });
            }}
          />
        </label>
        <label className="field">
          <span>To</span>
          <input
            type="datetime-local"
            value={toLocalInput(filters.to)}
            onChange={(event) => {
              onChange({ ...filters, to: fromLocalInput(event.target.value) });
            }}
          />
        </label>
      </div>
      {tooLong && (
        <p className="notice notice--warn" role="alert">
          That window is longer than {MAX_EVENT_WINDOW_DAYS} days, which the service refuses. Shorten it
          or use a preset.
        </p>
      )}
      {pinned && (
        <button
          type="button"
          className="button button--small"
          onClick={() => {
            onChange({ ...filters, from: null, to: null });
          }}
        >
          Back to the last {filters.windowHours} h
        </button>
      )}

      <label className="field">
        <span>Event type</span>
        <select
          value={filters.eventType ?? ''}
          onChange={(event) => {
            onChange({ ...filters, eventType: event.target.value === '' ? null : event.target.value });
          }}
        >
          <option value="">any</option>
          {eventTypeOptions.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </label>
      {eventTypeOptions.length === 0 && (
        <p className="muted">Event types are listed once events have been loaded.</p>
      )}

      <label className="field">
        <span>Source</span>
        <select
          value={filters.sourceType ?? ''}
          onChange={(event) => {
            onChange({ ...filters, sourceType: event.target.value === '' ? null : event.target.value });
          }}
        >
          <option value="">any</option>
          {['device', 'sensor', 'external', 'manual'].map((source) => (
            <option key={source} value={source}>
              {source}
            </option>
          ))}
        </select>
      </label>
      {knownSourceTypes.length > 0 && (
        <p className="muted">In view: {knownSourceTypes.join(', ')}</p>
      )}

      <dl className="facts">
        <dt>Events in view</dt>
        <dd>
          {count}
          {truncated && <span className="muted"> (first pages)</span>}
        </dd>
        {answeredWindow !== null && (
          <>
            <dt>Window answered</dt>
            <dd>
              {formatInstant(answeredWindow.from)} — {formatInstant(answeredWindow.to)}
            </dd>
          </>
        )}
        {loadedAt !== null && (
          <>
            <dt>Loaded</dt>
            <dd>{loadedAt.toLocaleTimeString()}</dd>
          </>
        )}
      </dl>
      <p className="muted">A window longer than {MAX_EVENT_WINDOW_DAYS} days is refused by the service.</p>
    </section>
  );
}
