/**
 * The geofence editor: draw, adjust, validate, save.
 *
 * A geofence here is an area on a map with a name, a period and a sharing policy - nothing about who is
 * told what (ADR-0012). The editor keeps a draft definition, draws it, checks it against the same rules
 * the service applies, and sends it; what the service says about a request it refuses is shown as it
 * came back, with its problem code.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { meanRadiusM, webMercatorCentre, type Bounds } from '../../geo/geometry';
import { ApiError } from '../../services/apiClient';
import type { GisApi } from '../../services/gisApi';
import type { Geofence, GeofenceStatus, SharingPolicy } from '../../types/api';
import {
  definitionFromDrawn,
  describeDraft,
  draftAreaM2,
  draftFromGeofence,
  draftToInput,
  emptyDraft,
  formatArea,
  MAX_CIRCLE_RADIUS_M,
  parseTenants,
  MAX_CORRIDOR_HALF_WIDTH_M,
  validateDraft,
  type DraftKind,
  type GeofenceDraft,
} from './geofenceDraft';
import { fromLocalInput, toLocalInput } from './localTime';
import type { DrawnShape, TerraDrawController } from './useTerraDraw';

const KINDS: readonly { readonly kind: DraftKind; readonly label: string; readonly hint: string }[] = [
  { kind: 'polygon', label: 'Polygon', hint: 'Click each corner; click the first one again to close.' },
  { kind: 'circle', label: 'Circle', hint: 'Click the centre, then click again at the radius.' },
  { kind: 'corridor', label: 'Corridor', hint: 'Click along the centre line; double-click to finish.' },
];

const STATUSES: readonly GeofenceStatus[] = ['draft', 'active', 'suspended'];
const POLICIES: readonly SharingPolicy[] = ['private', 'shared', 'authority_only'];

/** The editor's side of the shared Terra Draw instance (see `useTerraDraw`). */
export interface GeofenceDrawHandlers {
  readonly onFinish: (shape: DrawnShape) => void;
  /** A feature Terra Draw holds changed (`null`: deleted); only the editor's own shape matters. */
  readonly onChange: (id: string, shape: DrawnShape | null) => void;
}

export interface GeofenceEditorProps {
  readonly api: GisApi;
  /** The one Terra Draw instance of the map, owned by `MapContainer`. */
  readonly draw: TerraDrawController;
  /** Registers the editor's handlers with the map's drawing router; `null` on unmount. */
  readonly registerDrawHandlers: (handlers: GeofenceDrawHandlers | null) => void;
  readonly tenantId: string | null;
  readonly serviceAreaBounds: Bounds | null;
  /**
   * The geofence to edit, e.g. the one selected on the map. The editor is keyed on its id by the
   * container, so a different geofence mounts a fresh editor rather than being copied into this one.
   */
  readonly initialGeofence: Geofence | null;
  readonly onDraftChange: (draft: GeofenceDraft | null) => void;
  readonly onSaved: (geofence: Geofence | null) => void;
  readonly onClose: () => void;
}

export function GeofenceEditor({
  api,
  draw,
  registerDrawHandlers,
  tenantId,
  serviceAreaBounds,
  initialGeofence,
  onDraftChange,
  onSaved,
  onClose,
}: GeofenceEditorProps) {
  const [draft, setDraft] = useState<GeofenceDraft>(() =>
    initialGeofence === null ? emptyDraft('polygon') : draftFromGeofence(initialGeofence),
  );
  // Which feature Terra Draw is holding, and what kind the draft is: both are needed inside the draw
  // callbacks, which are not re-created per render.
  const drawnIdRef = useRef<string | null>(null);
  const kindRef = useRef<DraftKind>(draft.kind);
  // The list of tenants is edited as text: splitting it on every keystroke would eat the separators.
  const [sharedText, setSharedText] = useState(() => draft.sharedWithTenants.join(', '));
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<{ message: string; code: string | null } | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const { ready: drawReady, setMode, clear: clearDraw, load: loadDraw, remove: removeDrawn } = draw;

  const handleFinish = useCallback(
    (shape: DrawnShape) => {
      const kind = kindRef.current;
      const definition = definitionFromDrawn(kind, shape, webMercatorCentre, meanRadiusM);
      if (definition === null) {
        return;
      }
      setDraft((current) => ({
        ...current,
        geometry: definition.geometry,
        // A circle keeps the radius it was drawn with; the operator can then type an exact one.
        radiusM: definition.radiusM ?? current.radiusM,
      }));
      if (kind === 'circle') {
        // A circle is stored as a centre and a radius, so the drawn ring has served its purpose: the
        // map draws the exact circle from the definition instead. The editor no longer holds a shape
        // in Terra Draw, so the deletion Terra Draw reports next is not the operator removing the draft.
        drawnIdRef.current = null;
        removeDrawn(shape.id);
        setMode('static', 'geofence');
      } else {
        drawnIdRef.current = shape.id;
        setMode('select', 'geofence');
      }
    },
    [removeDrawn, setMode],
  );

  const handleChange = useCallback((id: string, shape: DrawnShape | null) => {
    if (drawnIdRef.current === null || id !== drawnIdRef.current) {
      // Not the shape the editor holds: the handles Terra Draw adds to a selected shape and removes when
      // it is deselected, the shape being drawn before it is finished (Escape discards it), the ring of a
      // finished circle, or what the editor itself cleared.
      return;
    }
    if (shape === null) {
      drawnIdRef.current = null;
      setDraft((current) => ({ ...current, geometry: null }));
      return;
    }
    const definition = definitionFromDrawn(kindRef.current, shape, webMercatorCentre, meanRadiusM);
    if (definition === null) {
      return;
    }
    setDraft((current) => ({
      ...current,
      geometry: definition.geometry,
      radiusM: definition.radiusM ?? current.radiusM,
    }));
  }, []);

  useEffect(() => {
    kindRef.current = draft.kind;
  }, [draft.kind]);

  useEffect(() => {
    registerDrawHandlers({ onFinish: handleFinish, onChange: handleChange });
    return () => {
      registerDrawHandlers(null);
    };
  }, [registerDrawHandlers, handleFinish, handleChange]);

  useEffect(() => {
    onDraftChange(draft);
    return () => {
      onDraftChange(null);
    };
  }, [draft, onDraftChange]);

  // The draft as it is now, for handing to a Terra Draw instance that has just become ready.
  const draftRef = useRef(draft);
  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  // The draft's shape is handed to Terra Draw so its vertices can be moved: a geofence opened for editing
  // when the editor mounts, and the shape as edited so far when Terra Draw starts again (a new basemap
  // replaces its instance). A circle is not, because its definition is a centre and a radius rather than
  // a ring. The editor lets go of its shape before clearing, so the deletions Terra Draw reports for the
  // clear are not taken as the operator removing it.
  useEffect(() => {
    if (!drawReady) {
      return;
    }
    const { geometry, kind } = draftRef.current;
    drawnIdRef.current = null;
    clearDraw();
    if (geometry !== null && kind !== 'circle') {
      const id = loadDraw(geometry);
      drawnIdRef.current = id;
      setMode(id === null ? 'static' : 'select', 'geofence');
    } else {
      setMode('static', 'geofence');
    }
  }, [drawReady, clearDraw, loadDraw, setMode]);

  const issues = useMemo(
    () => validateDraft(draft, serviceAreaBounds),
    [draft, serviceAreaBounds],
  );
  const area = draftAreaM2(draft);

  const startDrawing = (kind: DraftKind) => {
    setProblem(null);
    setSaved(null);
    drawnIdRef.current = null;
    clearDraw();
    kindRef.current = kind;
    setDraft((current) => ({
      ...current,
      kind,
      geometry: null,
      radiusM: emptyDraft(kind).radiusM,
    }));
    setMode(kind, 'geofence');
  };

  const clearShape = () => {
    drawnIdRef.current = null;
    clearDraw();
    setDraft((current) => ({ ...current, geometry: null }));
    setMode('static', 'geofence');
  };

  const reset = () => {
    drawnIdRef.current = null;
    clearDraw();
    setDraft(emptyDraft('polygon'));
    setProblem(null);
    setSaved(null);
    setMode('static', 'geofence');
  };

  const save = async () => {
    if (issues.length > 0 || draft.geometry === null) {
      return;
    }
    setSaving(true);
    setProblem(null);
    setSaved(null);
    try {
      const body = draftToInput(draft);
      const geofence =
        draft.id === null || draft.version === null
          ? await api.createGeofence(body, { tenantId })
          : await api.replaceGeofence(draft.id, { ...body, version: draft.version }, { tenantId });
      setDraft(draftFromGeofence(geofence));
      setSaved(`Saved as version ${geofence.version}.`);
      onSaved(geofence);
    } catch (error: unknown) {
      setProblem(describeError(error));
    } finally {
      setSaving(false);
    }
  };

  const archive = async (purge: boolean) => {
    if (draft.id === null) {
      return;
    }
    setSaving(true);
    setProblem(null);
    try {
      await api.deleteGeofence(draft.id, {
        tenantId,
        purge,
        ...(draft.version === null ? {} : { version: draft.version }),
      });
      onSaved(null);
      reset();
      setSaved(purge ? 'The geofence was deleted.' : 'The geofence was archived.');
    } catch (error: unknown) {
      setProblem(describeError(error));
    } finally {
      setSaving(false);
    }
  };

  const radiusLabel = draft.kind === 'corridor' ? 'Half-width (m)' : 'Radius (m)';
  const radiusMax = draft.kind === 'corridor' ? MAX_CORRIDOR_HALF_WIDTH_M : MAX_CIRCLE_RADIUS_M;
  const hint = KINDS.find((entry) => entry.kind === draft.kind)?.hint ?? '';

  return (
    <section className="panel" aria-labelledby="geofence-editor-heading">
      <header className="panel__header">
        <h2 id="geofence-editor-heading">Geofence editor</h2>
        <button type="button" className="button" onClick={onClose}>
          Close
        </button>
      </header>

      <div className="field-row" role="group" aria-label="Shape">
        {KINDS.map((entry) => (
          <button
            key={entry.kind}
            type="button"
            className={`button ${draft.kind === entry.kind ? 'button--active' : ''}`}
            aria-pressed={draft.kind === entry.kind}
            onClick={() => {
              startDrawing(entry.kind);
            }}
            disabled={!draw.ready}
          >
            {entry.label}
          </button>
        ))}
      </div>
      {!draw.ready && <p className="muted">Waiting for the map before drawing can start…</p>}
      <p className="muted">
        {draw.mode === draft.kind && draw.purpose === 'geofence' ? hint : describeDraft(draft)}
      </p>
      {area !== null && <p className="muted">Area {formatArea(area)}</p>}

      <label className="field">
        <span>Name</span>
        <input
          type="text"
          value={draft.name}
          maxLength={200}
          onChange={(event) => {
            setDraft((current) => ({ ...current, name: event.target.value }));
          }}
        />
      </label>

      <label className="field">
        <span>Description</span>
        <textarea
          rows={2}
          value={draft.description}
          maxLength={1000}
          onChange={(event) => {
            setDraft((current) => ({ ...current, description: event.target.value }));
          }}
        />
      </label>

      {draft.kind !== 'polygon' && (
        <label className="field">
          <span>{radiusLabel}</span>
          <input
            type="number"
            min={1}
            max={radiusMax}
            step={1}
            value={draft.radiusM ?? ''}
            onChange={(event) => {
              const value = Number(event.target.value);
              setDraft((current) => ({
                ...current,
                radiusM: event.target.value === '' ? null : value,
              }));
            }}
          />
        </label>
      )}

      <div className="field-row">
        <label className="field">
          <span>Status</span>
          <select
            value={draft.status}
            onChange={(event) => {
              setDraft((current) => ({ ...current, status: event.target.value as GeofenceStatus }));
            }}
          >
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Sharing</span>
          <select
            value={draft.sharingPolicy}
            onChange={(event) => {
              setDraft((current) => ({
                ...current,
                sharingPolicy: event.target.value as SharingPolicy,
              }));
            }}
          >
            {POLICIES.map((policy) => (
              <option key={policy} value={policy}>
                {policy}
              </option>
            ))}
          </select>
        </label>
      </div>

      {draft.sharingPolicy === 'shared' && (
        <label className="field">
          <span>Shared with tenants</span>
          <input
            type="text"
            value={sharedText}
            placeholder="forest-dept, police"
            onChange={(event) => {
              setSharedText(event.target.value);
              setDraft((current) => ({
                ...current,
                sharedWithTenants: parseTenants(event.target.value),
              }));
            }}
          />
        </label>
      )}

      <div className="field-row">
        <label className="field">
          <span>In effect from</span>
          <input
            type="datetime-local"
            value={toLocalInput(draft.effectiveFrom)}
            onChange={(event) => {
              setDraft((current) => ({ ...current, effectiveFrom: fromLocalInput(event.target.value) }));
            }}
          />
        </label>
        <label className="field">
          <span>until</span>
          <input
            type="datetime-local"
            value={toLocalInput(draft.effectiveTo)}
            onChange={(event) => {
              setDraft((current) => ({ ...current, effectiveTo: fromLocalInput(event.target.value) }));
            }}
          />
        </label>
      </div>

      {issues.length > 0 && (
        <ul className="issues" aria-label="Validation problems">
          {issues.map((issue) => (
            <li key={`${issue.field}:${issue.message}`} className="issues__item">
              {issue.message}
            </li>
          ))}
        </ul>
      )}

      {problem !== null && (
        <p className="notice notice--error" role="alert">
          {problem.message}
          {problem.code !== null && <span className="muted"> ({problem.code})</span>}
        </p>
      )}
      {saved !== null && (
        <p className="notice notice--ok" role="status">
          {saved}
        </p>
      )}

      <div className="field-row">
        <button
          type="button"
          className="button button--primary"
          onClick={() => {
            void save();
          }}
          disabled={saving || issues.length > 0}
        >
          {draft.id === null ? 'Create geofence' : `Save version ${(draft.version ?? 0) + 1}`}
        </button>
        <button type="button" className="button" onClick={clearShape} disabled={draft.geometry === null}>
          Clear shape
        </button>
        <button type="button" className="button" onClick={reset}>
          New
        </button>
      </div>

      {draft.id !== null && (
        <div className="field-row">
          <button
            type="button"
            className="button"
            onClick={() => {
              void archive(false);
            }}
            disabled={saving}
          >
            Archive
          </button>
          <button
            type="button"
            className="button button--danger"
            onClick={() => {
              void archive(true);
            }}
            disabled={saving}
          >
            Delete permanently
          </button>
        </div>
      )}
    </section>
  );
}

function describeError(error: unknown): { message: string; code: string | null } {
  if (error instanceof ApiError) {
    const current = error.extensions.currentVersion;
    const suffix = typeof current === 'number' ? ` The geofence is now at version ${current}.` : '';
    return { message: `${error.summary}${suffix}`, code: error.code };
  }
  return { message: error instanceof Error ? error.message : String(error), code: null };
}
