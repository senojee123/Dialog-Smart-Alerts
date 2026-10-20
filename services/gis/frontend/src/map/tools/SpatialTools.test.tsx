import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { layerCatalogue } from '../../test/fixtures';
import { SpatialTools } from './SpatialTools';
import type { SpatialTools as SpatialToolsState } from './useSpatialTools';

function toolsState(overrides: Partial<SpatialToolsState> = {}): SpatialToolsState {
  return {
    tool: null,
    target: 'ref.settlement',
    stale: false,
    radiusM: 1000,
    nearestLimit: 10,
    centre: null,
    measure: [],
    results: [],
    rows: [],
    status: 'idle',
    error: null,
    truncated: false,
    circle: null,
    selectTool: vi.fn(),
    setTarget: vi.fn(),
    setRadiusM: vi.fn(),
    setNearestLimit: vi.fn(),
    handleClick: vi.fn(),
    undoMeasure: vi.fn(),
    clearResults: vi.fn(),
    rerun: vi.fn(),
    ...overrides,
  };
}

function renderTools(state: SpatialToolsState) {
  const onClearFilter = vi.fn();
  const onFocus = vi.fn();
  render(
    <SpatialTools
      tools={state}
      catalogue={layerCatalogue}
      filterActive={false}
      onClearFilter={onClearFilter}
      onFocus={onFocus}
    />,
  );
  return { onClearFilter, onFocus };
}

describe('SpatialTools', () => {
  it('offers the four tools and arms the one that was chosen', async () => {
    const state = toolsState();
    renderTools(state);
    for (const label of ['Radius search', 'Nearby devices', 'Measure', 'Draw to filter']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
    await userEvent.click(screen.getByRole('button', { name: 'Radius search' }));
    expect(state.selectTool).toHaveBeenCalledWith('radius');
  });

  it('disarms a tool that is armed again', async () => {
    const state = toolsState({ tool: 'measure' });
    renderTools(state);
    await userEvent.click(screen.getByRole('button', { name: 'Measure' }));
    expect(state.selectTool).toHaveBeenCalledWith(null);
  });

  it('offers only the layers the service says can answer a distance query', () => {
    renderTools(toolsState({ tool: 'radius' }));
    const options = [...screen.getByLabelText('Layer to search').querySelectorAll('option')].map(
      (option) => option.textContent,
    );
    expect(options).toEqual([
      'Administrative areas',
      'Settlements',
      'Roads',
      'Water',
      'Protected areas',
      'Geofences',
      'Fields of view',
      'Devices',
    ]);
  });

  it('sets a distance from a preset or by hand', async () => {
    const state = toolsState({ tool: 'radius' });
    renderTools(state);
    await userEvent.click(screen.getByRole('button', { name: '500 m' }));
    expect(state.setRadiusM).toHaveBeenCalledWith(500);
    await userEvent.clear(screen.getByLabelText('Distance (m)'));
    await userEvent.type(screen.getByLabelText('Distance (m)'), '3000');
    expect(state.setRadiusM).toHaveBeenCalled();
  });

  it('measures in EPSG:5235 metres and says so', () => {
    renderTools(
      toolsState({
        tool: 'measure',
        measure: [
          [80.75, 8.03],
          [80.76, 8.03],
        ],
      }),
    );
    expect(screen.getByText(/over 2 positions/)).toBeInTheDocument();
    // The hint and the note both name the plane the distances are measured on.
    expect(screen.getAllByText(/EPSG:5235/)).toHaveLength(2);
  });

  it('lists the results and focuses the one that was clicked', async () => {
    const state = toolsState({
      tool: 'radius',
      status: 'done',
      rows: [
        { id: 'a', name: 'Habarana', distanceM: 512.34, relation: null, position: [80.75, 8.03], detail: 'town' },
        { id: 'b', name: 'Palugaswewa', distanceM: 2400, relation: null, position: null, detail: 'village' },
      ],
    });
    const { onFocus } = renderTools(state);
    expect(screen.getByRole('heading', { name: '2 results' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Habarana' }));
    expect(onFocus).toHaveBeenCalledWith([80.75, 8.03]);
    expect(screen.getByRole('button', { name: 'Palugaswewa' })).toBeDisabled();
    expect(screen.getByText('512 m')).toBeInTheDocument();
  });

  it('says when a search found nothing, and when it failed', () => {
    const { rerender } = render(
      <SpatialTools
        tools={toolsState({ tool: 'radius', status: 'done' })}
        catalogue={layerCatalogue}
        filterActive={false}
        onClearFilter={vi.fn()}
        onFocus={vi.fn()}
      />,
    );
    expect(screen.getByText('Nothing found within the distance searched.')).toBeInTheDocument();
    rerender(
      <SpatialTools
        tools={toolsState({ tool: 'radius', status: 'error', error: 'Layer not found (layer_not_found)' })}
        catalogue={layerCatalogue}
        filterActive={false}
        onClearFilter={vi.fn()}
        onFocus={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('layer_not_found');
  });

  it('offers to run the search again when the settings have changed since the answer', async () => {
    const state = toolsState({
      tool: 'radius',
      status: 'done',
      stale: true,
      rows: [
        { id: 'a', name: 'Habarana', distanceM: 512.34, relation: null, position: [80.75, 8.03], detail: 'town' },
      ],
    });
    renderTools(state);
    expect(screen.getByRole('status')).toHaveTextContent('previous search');
    await userEvent.click(screen.getByRole('button', { name: 'Search again' }));
    expect(state.rerun).toHaveBeenCalled();
  });

  it('keeps a typed distance inside what the API accepts', () => {
    const state = toolsState({ tool: 'radius' });
    renderTools(state);
    fireEvent.change(screen.getByLabelText('Distance (m)'), { target: { value: '999999' } });
    expect(state.setRadiusM).toHaveBeenLastCalledWith(100_000);
    fireEvent.change(screen.getByLabelText('Distance (m)'), { target: { value: '' } });
    expect(state.setRadiusM).toHaveBeenLastCalledWith(1);
  });

  it('clears the area that was drawn to filter by', async () => {
    const onClearFilter = vi.fn();
    render(
      <SpatialTools
        tools={toolsState({ tool: 'filter' })}
        catalogue={layerCatalogue}
        filterActive
        onClearFilter={onClearFilter}
        onFocus={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Clear filter area' }));
    expect(onClearFilter).toHaveBeenCalled();
  });
});
