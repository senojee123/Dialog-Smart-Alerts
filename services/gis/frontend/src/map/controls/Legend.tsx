/**
 * The legend: what the colours on the map mean, for the layers that are actually on.
 */
import type { CSSProperties } from 'react';

import { MAP_LAYERS, type LegendEntry, type MapLayerDefinition } from '../layers/layerCatalogue';

export interface LegendProps {
  readonly visible: ReadonlySet<string>;
  readonly availableLayers: readonly MapLayerDefinition[];
}

export function Legend({ visible, availableLayers }: LegendProps) {
  const known = new Set(availableLayers.map((layer) => layer.id));
  const layers = MAP_LAYERS.filter((layer) => visible.has(layer.id) && known.has(layer.id));

  if (layers.length === 0) {
    return (
      <section className="legend" aria-label="Legend">
        <p className="muted">No layers are shown.</p>
      </section>
    );
  }

  return (
    <section className="legend" aria-label="Legend">
      <h2 className="legend__heading">Legend</h2>
      <ul className="legend__list">
        {layers.map((layer) => (
          <li key={layer.id} className="legend__layer">
            <span className="legend__title">{layer.title}</span>
            <ul className="legend__entries">
              {layer.legend.map((entry) => (
                <li key={`${layer.id}-${entry.label}`} className="legend__entry">
                  <Swatch entry={entry} />
                  <span>{entry.label}</span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Swatch({ entry }: { readonly entry: LegendEntry }) {
  return (
    <span
      className={`swatch swatch--${entry.shape}`}
      style={{ '--swatch-colour': entry.colour } as CSSProperties}
      aria-hidden="true"
    />
  );
}
