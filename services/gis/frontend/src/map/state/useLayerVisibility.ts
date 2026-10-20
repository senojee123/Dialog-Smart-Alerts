/**
 * Which layers are shown. The map asks the API only for layers that are visible, so turning a layer off
 * is also what stops it being loaded.
 */
import { useCallback, useMemo, useState } from 'react';

import { MAP_LAYERS, type LayerGroupId, type MapLayerDefinition } from '../layers/layerCatalogue';

export interface LayerVisibility {
  readonly visible: ReadonlySet<string>;
  isVisible(id: string): boolean;
  toggle(id: string): void;
  set(id: string, visible: boolean): void;
  setGroup(group: LayerGroupId, visible: boolean): void;
  reset(): void;
}

export function defaultVisibleLayers(
  layers: readonly MapLayerDefinition[] = MAP_LAYERS,
): ReadonlySet<string> {
  return new Set(layers.filter((layer) => layer.defaultVisible).map((layer) => layer.id));
}

export function useLayerVisibility(
  initial: ReadonlySet<string> = defaultVisibleLayers(),
  layers: readonly MapLayerDefinition[] = MAP_LAYERS,
): LayerVisibility {
  const [visible, setVisible] = useState<ReadonlySet<string>>(initial);

  const set = useCallback((id: string, next: boolean) => {
    setVisible((current) => {
      const updated = new Set(current);
      if (next) {
        updated.add(id);
      } else {
        updated.delete(id);
      }
      return updated;
    });
  }, []);

  const toggle = useCallback((id: string) => {
    setVisible((current) => {
      const updated = new Set(current);
      if (updated.has(id)) {
        updated.delete(id);
      } else {
        updated.add(id);
      }
      return updated;
    });
  }, []);

  const setGroup = useCallback(
    (group: LayerGroupId, next: boolean) => {
      setVisible((current) => {
        const updated = new Set(current);
        for (const layer of layers.filter((candidate) => candidate.group === group)) {
          if (next) {
            updated.add(layer.id);
          } else {
            updated.delete(layer.id);
          }
        }
        return updated;
      });
    },
    [layers],
  );

  const reset = useCallback(() => {
    setVisible(defaultVisibleLayers(layers));
  }, [layers]);

  return useMemo(
    () => ({
      visible,
      isVisible: (id: string) => visible.has(id),
      toggle,
      set,
      setGroup,
      reset,
    }),
    [visible, toggle, set, setGroup, reset],
  );
}
