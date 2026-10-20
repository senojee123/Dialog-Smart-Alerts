/**
 * The popup for the selected feature: what it is, what the service says about it, and where it is.
 *
 * "Where it is" is the geographic context: for an event, the administrative codes its geo-context
 * recorded, resolved to names through `GET /geo/v1/reverse`, with the nearest settlement and road. It is
 * geography, not advice - the popup says what is there, and nothing about what should be done.
 */
import { Popup } from 'react-map-gl/maplibre';

import type { DeviceState } from '../palette';
import { DEVICE_LAYER_ID, GEOFENCE_LAYER_ID, layerById } from '../layers/layerCatalogue';
import type { Selection } from '../state/mapState';
import type { ReverseGeocodeState } from '../state/useReverseGeocode';
import { formatMetres } from '../editor/geofenceDraft';
import {
  adminCodesOf,
  isEventLayer,
  summaryRows,
  titleOf,
  type SummaryRow,
} from './featureSummary';

const DEVICE_STATE_LABELS: Readonly<Record<DeviceState, string>> = {
  online: 'Online',
  degraded: 'Degraded',
  offline: 'Offline',
  unknown: 'Not reported',
};

export interface FeaturePopupProps {
  readonly selection: Selection;
  readonly context: ReverseGeocodeState;
  readonly onClose: () => void;
  readonly onRequestContext: () => void;
  readonly onEditGeofence?: (geofenceId: string) => void;
  readonly deviceState?: (deviceId: string) => DeviceState | undefined;
}

export function FeaturePopup({
  selection,
  context,
  onClose,
  onRequestContext,
  onEditGeofence,
  deviceState,
}: FeaturePopupProps) {
  const layer = layerById(selection.layerId);
  const title = titleOf(selection.layerId, selection.properties, selection.featureId);
  const rows = summaryRows(selection.properties);
  const codes = adminCodesOf(selection.properties);
  const isEvent = isEventLayer(selection.layerId);
  const isDevice = selection.layerId === DEVICE_LAYER_ID;
  const isGeofence = selection.layerId === GEOFENCE_LAYER_ID;
  const state = isDevice ? (deviceState?.(selection.featureId) ?? 'unknown') : null;

  return (
    <Popup
      longitude={selection.position[0]}
      latitude={selection.position[1]}
      anchor="bottom"
      closeOnClick={false}
      onClose={onClose}
      maxWidth="340px"
    >
      <div className="popup">
        <h3 className="popup__title">{title}</h3>
        <p className="popup__layer">{layer?.title ?? selection.layerId}</p>

        {state !== null && (
          <p className={`popup__state popup__state--${state}`}>
            Reported state: {DEVICE_STATE_LABELS[state]}
            {state === 'unknown' && (
              <span className="muted"> — device health comes from another service</span>
            )}
          </p>
        )}

        {rows.length > 0 && (
          <dl className="popup__facts">
            {rows.map((row: SummaryRow) => (
              <div key={row.key} className="popup__fact">
                <dt>{row.label}</dt>
                <dd>{row.value}</dd>
              </div>
            ))}
          </dl>
        )}

        <h4 className="popup__section">Geographic context</h4>
        {codes !== null && (
          <p className="popup__codes">
            Recorded codes: {[codes.l1, codes.l2, codes.l3, codes.l4].filter((code) => code !== null).join(' · ')}
          </p>
        )}
        {context.status === 'idle' && (
          <button type="button" className="button" onClick={onRequestContext}>
            Resolve this position
          </button>
        )}
        {context.status === 'loading' && <p className="muted">Resolving…</p>}
        {context.status === 'error' && (
          <p className="notice notice--error" role="alert">
            {context.error}
          </p>
        )}
        {context.data !== null && (
          <dl className="popup__facts">
            {context.data.admin.province !== null && (
              <div className="popup__fact">
                <dt>Province</dt>
                <dd>{context.data.admin.province.name}</dd>
              </div>
            )}
            {context.data.admin.district !== null && (
              <div className="popup__fact">
                <dt>District</dt>
                <dd>{context.data.admin.district.name}</dd>
              </div>
            )}
            {context.data.admin.dsDivision !== null && (
              <div className="popup__fact">
                <dt>DS division</dt>
                <dd>{context.data.admin.dsDivision.name}</dd>
              </div>
            )}
            {context.data.admin.gnDivision !== null && (
              <div className="popup__fact">
                <dt>GN division</dt>
                <dd>{context.data.admin.gnDivision.name}</dd>
              </div>
            )}
            {context.data.nearestSettlement !== null && (
              <div className="popup__fact">
                <dt>Nearest settlement</dt>
                <dd>
                  {context.data.nearestSettlement.name} ·{' '}
                  {formatMetres(context.data.nearestSettlement.distanceM)}
                </dd>
              </div>
            )}
            {context.data.nearestRoad !== null && (
              <div className="popup__fact">
                <dt>Nearest road</dt>
                <dd>
                  {context.data.nearestRoad.refCode ?? context.data.nearestRoad.name ?? 'unnamed'} ·{' '}
                  {formatMetres(context.data.nearestRoad.distanceM)}
                </dd>
              </div>
            )}
            <div className="popup__fact">
              <dt>Release</dt>
              <dd>{context.data.refDataRelease}</dd>
            </div>
            {context.data.admin.onBoundary && (
              <div className="popup__fact">
                <dt>On a boundary</dt>
                <dd>the area with the lowest code was chosen</dd>
              </div>
            )}
          </dl>
        )}

        {isEvent && <p className="muted">Event as the service recorded it; its geo-context is above.</p>}

        {isGeofence && onEditGeofence !== undefined && (
          <button
            type="button"
            className="button button--primary"
            onClick={() => {
              onEditGeofence(selection.featureId);
            }}
          >
            Edit this geofence
          </button>
        )}

        <p className="popup__position">
          {selection.position[1].toFixed(5)}, {selection.position[0].toFixed(5)}
        </p>
      </div>
    </Popup>
  );
}
