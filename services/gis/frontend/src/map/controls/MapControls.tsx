/**
 * Layer visibility and basemap: what the operator turns on and off.
 *
 * A layer that is off is not requested, so this panel controls the load as well as the view.
 */
import type { Basemap } from '../../config';
import {
  LAYER_GROUPS,
  MAP_LAYERS,
  type LayerGroupId,
  type MapLayerDefinition,
} from '../layers/layerCatalogue';
import type { LayerReport } from '../layers/LayerManager';
import type { LayerVisibility } from '../state/useLayerVisibility';

export interface MapControlsProps {
  readonly visibility: LayerVisibility;
  readonly availableLayers: readonly MapLayerDefinition[];
  readonly reports: Readonly<Record<string, LayerReport>>;
  readonly basemaps: readonly Basemap[];
  readonly basemapId: string;
  readonly onBasemapChange: (id: string) => void;
  readonly showLabels: boolean;
  readonly onShowLabelsChange: (show: boolean) => void;
  readonly onRefresh: () => void;
}

function statusNote(report: LayerReport | undefined): string {
  if (report === undefined) {
    return '';
  }
  switch (report.reason) {
    case 'zoom':
      return 'zoom in';
    case 'outside':
      return 'off area';
    case 'hidden':
      return '';
    default:
      break;
  }
  if (report.status === 'loading') {
    return '…';
  }
  if (report.status === 'error') {
    return 'failed';
  }
  return report.truncated ? `${report.count}+` : String(report.count);
}

export function MapControls({
  visibility,
  availableLayers,
  reports,
  basemaps,
  basemapId,
  onBasemapChange,
  showLabels,
  onShowLabelsChange,
  onRefresh,
}: MapControlsProps) {
  const known = new Set(availableLayers.map((layer) => layer.id));

  return (
    <section className="panel" aria-labelledby="layers-heading">
      <header className="panel__header">
        <h2 id="layers-heading">Layers</h2>
        <button type="button" className="button" onClick={onRefresh}>
          Refresh
        </button>
      </header>

      {LAYER_GROUPS.map((group) => (
        <LayerGroup
          key={group.id}
          id={group.id}
          title={group.title}
          layers={MAP_LAYERS.filter((layer) => layer.group === group.id && known.has(layer.id))}
          visibility={visibility}
          reports={reports}
        />
      ))}

      <label className="field">
        <span>Basemap</span>
        <select
          value={basemapId}
          onChange={(event) => {
            onBasemapChange(event.target.value);
          }}
        >
          {basemaps.map((basemap) => (
            <option key={basemap.id} value={basemap.id}>
              {basemap.label}
            </option>
          ))}
        </select>
      </label>

      <label className="toggle">
        <input
          type="checkbox"
          checked={showLabels}
          onChange={(event) => {
            onShowLabelsChange(event.target.checked);
          }}
        />
        <span>Show labels</span>
      </label>
    </section>
  );
}

interface LayerGroupProps {
  readonly id: LayerGroupId;
  readonly title: string;
  readonly layers: readonly MapLayerDefinition[];
  readonly visibility: LayerVisibility;
  readonly reports: Readonly<Record<string, LayerReport>>;
}

function LayerGroup({ id, title, layers, visibility, reports }: LayerGroupProps) {
  if (layers.length === 0) {
    return null;
  }
  const allOn = layers.every((layer) => visibility.isVisible(layer.id));

  return (
    <div className="layer-group">
      <div className="layer-group__header">
        <h3>{title}</h3>
        <button
          type="button"
          className="button button--small"
          onClick={() => {
            visibility.setGroup(id, !allOn);
          }}
        >
          {allOn ? 'None' : 'All'}
        </button>
      </div>
      <ul className="layer-list">
        {layers.map((layer) => {
          const report = reports[layer.id];
          return (
            <li key={layer.id} className="layer-list__item">
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={visibility.isVisible(layer.id)}
                  onChange={(event) => {
                    visibility.set(layer.id, event.target.checked);
                  }}
                />
                <span title={layer.description}>{layer.title}</span>
              </label>
              <span className="layer-list__count" aria-label={`${layer.title} features`}>
                {visibility.isVisible(layer.id) ? statusNote(report) : ''}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
