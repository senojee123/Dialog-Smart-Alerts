import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { NEUTRAL_BASEMAP } from '../../config';
import { MAP_LAYERS } from '../layers/layerCatalogue';
import type { LayerReport } from '../layers/LayerManager';
import type { LayerVisibility } from '../state/useLayerVisibility';
import { MapControls } from './MapControls';

function visibility(visible: Set<string>): LayerVisibility & { calls: unknown[] } {
  const calls: unknown[] = [];
  return {
    visible,
    isVisible: (id: string) => visible.has(id),
    toggle: (id: string) => calls.push(['toggle', id]),
    set: (id: string, next: boolean) => calls.push(['set', id, next]),
    setGroup: (group: string, next: boolean) => calls.push(['setGroup', group, next]),
    reset: () => calls.push(['reset']),
    calls,
  } as LayerVisibility & { calls: unknown[] };
}

const REPORTS: Record<string, LayerReport> = {
  events: { status: 'success', count: 12, error: null, truncated: false, refDataRelease: null, reason: null },
  devices: { status: 'loading', count: 0, error: null, truncated: false, refDataRelease: null, reason: null },
  roads: { status: 'idle', count: 0, error: null, truncated: false, refDataRelease: null, reason: 'zoom' },
  settlements: {
    status: 'success',
    count: 500,
    error: null,
    truncated: true,
    refDataRelease: 'ref-2026.09',
    reason: null,
  },
  geofences: { status: 'error', count: 0, error: new Error('nope'), truncated: false, refDataRelease: null, reason: null },
};

function renderControls(visible = new Set(['events', 'devices', 'roads', 'settlements', 'geofences'])) {
  const state = visibility(visible);
  const onBasemapChange = vi.fn();
  const onShowLabelsChange = vi.fn();
  const onRefresh = vi.fn();
  render(
    <MapControls
      visibility={state}
      availableLayers={MAP_LAYERS}
      reports={REPORTS}
      basemaps={[{ id: 'osm', label: 'OpenStreetMap', styleUrl: 'https://tiles.example/s.json' }, NEUTRAL_BASEMAP]}
      basemapId="osm"
      onBasemapChange={onBasemapChange}
      showLabels
      onShowLabelsChange={onShowLabelsChange}
      onRefresh={onRefresh}
    />,
  );
  return { state, onBasemapChange, onShowLabelsChange, onRefresh };
}

describe('MapControls', () => {
  it('groups the layers and checks the ones that are on', () => {
    renderControls(new Set(['events']));
    expect(screen.getByRole('heading', { name: 'Layers' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Events' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Operational' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Reference' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Events' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Devices' })).not.toBeChecked();
  });

  it('turns a layer on through the visibility it was given', async () => {
    const { state } = renderControls(new Set());
    await userEvent.click(screen.getByRole('checkbox', { name: 'Devices' }));
    expect(state.calls).toContainEqual(['set', 'devices', true]);
  });

  it('turns a whole group on and off', async () => {
    const { state } = renderControls(new Set());
    await userEvent.click(screen.getAllByRole('button', { name: 'All' })[0] as HTMLElement);
    expect(state.calls.some((call) => Array.isArray(call) && call[0] === 'setGroup')).toBe(true);
  });

  it('says what each layer is doing: a count, loading, a limit, a zoom or a failure', () => {
    renderControls();
    expect(screen.getByLabelText('Events features')).toHaveTextContent('12');
    expect(screen.getByLabelText('Devices features')).toHaveTextContent('…');
    expect(screen.getByLabelText('Roads features')).toHaveTextContent('zoom in');
    expect(screen.getByLabelText('Settlements features')).toHaveTextContent('500+');
    expect(screen.getByLabelText('Geofences features')).toHaveTextContent('failed');
  });

  it('switches the basemap and the labels, and reloads on request', async () => {
    const { onBasemapChange, onShowLabelsChange, onRefresh } = renderControls();
    await userEvent.selectOptions(screen.getByLabelText('Basemap'), NEUTRAL_BASEMAP.id);
    expect(onBasemapChange).toHaveBeenCalledWith(NEUTRAL_BASEMAP.id);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Show labels' }));
    expect(onShowLabelsChange).toHaveBeenCalledWith(false);
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('leaves out a layer the deployment does not publish', () => {
    render(
      <MapControls
        visibility={visibility(new Set())}
        availableLayers={MAP_LAYERS.filter((layer) => layer.id !== 'riskZones')}
        reports={{}}
        basemaps={[NEUTRAL_BASEMAP]}
        basemapId={NEUTRAL_BASEMAP.id}
        onBasemapChange={vi.fn()}
        showLabels={false}
        onShowLabelsChange={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );
    expect(screen.queryByRole('checkbox', { name: 'Risk zones' })).not.toBeInTheDocument();
  });
});
