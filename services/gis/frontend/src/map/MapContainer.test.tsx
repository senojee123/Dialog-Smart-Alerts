import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { DrawStub } from '../test/drawStub';

vi.mock('react-map-gl/maplibre', async () => (await import('../test/reactMapGl')).mapGlMock());
vi.mock('./maplibreSetup', () => ({
  configureMapLibre: () => ({}),
  supportsWebGL2: () => true,
}));
const drawing = vi.hoisted(() => ({
  recentlyFinished: false,
  /** What the container gave the hook, so a test can play Terra Draw finishing a shape. */
  options: null as null | {
    onFinish: (shape: { id: string; geometry: unknown; properties: object }, purpose: 'geofence' | 'filter') => void;
  },
  stub: null as null | DrawStub,
}));
vi.mock('./editor/useTerraDraw', async () => {
  const { drawStub } = await import('../test/drawStub');
  const stub = drawStub();
  stub.finishedRecently = () => drawing.recentlyFinished;
  drawing.stub = stub;
  return {
    useTerraDraw: (options: NonNullable<typeof drawing.options>) => {
      drawing.options = options;
      return stub;
    },
  };
});

import { ApiError } from '../services/apiClient';
import { apiStub } from '../test/apiStub';
import type { Geofence } from '../types/api';
import {
  deviceFeature,
  geofence,
  eventCollection,
  eventFeature,
  featureCollection,
  layerCatalogue,
  settlementFeature,
  viewer,
} from '../test/fixtures';
import { mapState, resetMapState } from '../test/reactMapGl';
import { MapContainer } from './MapContainer';
import { FEATURE_ID_PROPERTY, LAYER_ID_PROPERTY } from './sourceData';

beforeEach(() => {
  resetMapState();
  vi.clearAllMocks();
  drawing.recentlyFinished = false;
});

function api() {
  return apiStub({
    listFeatures: vi.fn((query: { layer: string }) =>
      Promise.resolve(
        featureCollection(
          query.layer === 'ops.device'
            ? [deviceFeature]
            : query.layer === 'ref.settlement'
              ? [settlementFeature]
              : [],
        ),
      ),
    ),
    listEvents: vi.fn(() => Promise.resolve(eventCollection([eventFeature]))),
  });
}

/** The map as MapLibre would report it after loading, so the client has a viewport. */
function loadMap() {
  const bounds = {
    getWest: () => 80.6,
    getSouth: () => 7.9,
    getEast: () => 80.9,
    getNorth: () => 8.2,
  };
  const instance = {
    getBounds: () => bounds,
    getZoom: () => 12,
    fitBounds: vi.fn(),
    easeTo: vi.fn(),
    getSource: () => undefined,
  };
  act(() => {
    mapState.props?.onLoad?.({ target: instance });
  });
  return instance;
}

function clickFeature(feature: { layerId: string; featureId: string; properties: Record<string, unknown>; geometry: unknown }) {
  act(() => {
    mapState.props?.onClick?.({
      lngLat: { lng: 80.75, lat: 8.03 },
      features: [
        {
          layer: { id: `${feature.layerId}-point` },
          geometry: feature.geometry,
          properties: {
            ...feature.properties,
            [FEATURE_ID_PROPERTY]: feature.featureId,
            [LAYER_ID_PROPERTY]: feature.layerId,
          },
        },
      ],
    });
  });
}

describe('MapContainer', () => {
  it('renders the map, the panels and the legend', async () => {
    render(<MapContainer api={api()} tenantId="wildlife-dept" />);
    expect(screen.getByTestId('map')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Layers' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Event filters' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Spatial tools' })).toBeInTheDocument();
    // Offered once the service has said the caller may use them.
    expect(await screen.findByRole('heading', { name: 'Geofences' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Export' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText('Legend')).toBeInTheDocument();
    });
  });

  it('offers a viewer the map, and nothing the service would refuse', async () => {
    const client = api();
    client.getIdentity.mockResolvedValue(viewer);
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    loadMap();
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: 'Event filters' })).not.toBeInTheDocument();
    });
    expect(screen.getByRole('heading', { name: 'Layers' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Geofences' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Export' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Events' })).not.toBeInTheDocument();
    // Measuring works in the browser; asking the service does not.
    expect(screen.getByRole('button', { name: 'Measure' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Radius search' })).not.toBeInTheDocument();
    clickFeature({
      layerId: 'geofences',
      featureId: 'gf-1',
      properties: { name: 'Watch zone' },
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
    });
    await waitFor(() => {
      expect(screen.getByTestId('popup')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Edit this geofence' })).not.toBeInTheDocument();
  });

  it('offers nothing that changes data while it does not know what the caller may do', async () => {
    const client = api();
    client.getIdentity.mockRejectedValue(new Error('offline'));
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    await waitFor(() => {
      expect(client.getIdentity).toHaveBeenCalled();
    });
    expect(screen.getByRole('heading', { name: 'Event filters' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Geofences' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Export' })).not.toBeInTheDocument();
  });

  it('renders no panels when the host asks for none', () => {
    render(<MapContainer api={api()} panels={[]} />);
    expect(screen.getByTestId('map')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Layers' })).not.toBeInTheDocument();
  });

  it('loads the visible layers for the window the map is showing', async () => {
    const client = api();
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    const instance = loadMap();
    await waitFor(() => {
      expect(instance.fitBounds).toHaveBeenCalled();
    });
    await waitFor(
      () => {
        expect(client.listFeatures).toHaveBeenCalled();
      },
      { timeout: 2000 },
    );
    const layers = client.listFeatures.mock.calls.map((call) => (call[0] as { layer: string }).layer);
    expect(layers).toContain('ref.settlement');
    expect(layers).toContain('ops.device');
    expect(layers).toContain('ops.geofence');
    // A layer that is off by default is not asked for at all.
    expect(layers).not.toContain('ref.facility');
    expect(client.listEvents).toHaveBeenCalled();
  });

  it('keeps offering every event type after the events are filtered to one of them', async () => {
    const intrusion = {
      ...eventFeature,
      id: 'evt-2026-09-000124',
      properties: { ...eventFeature.properties, eventId: 'evt-2026-09-000124', eventType: 'security.intrusion' },
    };
    const client = apiStub({
      listFeatures: vi.fn(() => Promise.resolve(featureCollection([]))),
      listEvents: vi.fn((query: { eventType?: string | null }) =>
        Promise.resolve(
          eventCollection(
            [eventFeature, intrusion].filter(
              (feature) => query.eventType == null || feature.properties.eventType === query.eventType,
            ),
          ),
        ),
      ),
    });
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    loadMap();
    const select = screen.getByLabelText('Event type');
    await waitFor(() => {
      expect(within(select).getByRole('option', { name: 'security.intrusion' })).toBeInTheDocument();
    });

    await userEvent.selectOptions(select, 'security.intrusion');
    await waitFor(() => {
      expect(client.listEvents).toHaveBeenLastCalledWith(
        expect.objectContaining({ eventType: 'security.intrusion' }),
        expect.anything(),
      );
    });
    // Only intrusions are loaded now, and the elephant detections can still be chosen.
    expect(select).toHaveValue('security.intrusion');
    const options = within(select)
      .getAllByRole('option')
      .map((option) => option.getAttribute('value'));
    expect(options).toEqual(['', 'security.intrusion', 'wildlife.elephant_detected']);
  });

  it('stays at a view it was asked to open at, instead of framing the service area', async () => {
    const client = api();
    const view = { longitude: 80.7565, latitude: 8.0423, zoom: 14 };
    render(<MapContainer api={client} tenantId="wildlife-dept" initialView={view} />);
    const instance = loadMap();
    await waitFor(() => {
      expect(client.listEvents).toHaveBeenCalled();
    });
    expect(instance.fitBounds).not.toHaveBeenCalled();
  });

  it('clusters events and draws every visible layer as its own source', async () => {
    render(<MapContainer api={api()} tenantId="wildlife-dept" />);
    loadMap();
    expect(await screen.findByTestId('source-events-points')).toHaveAttribute('data-cluster', 'yes');
    expect(await screen.findByTestId('source-devices-source')).toBeInTheDocument();
    expect(await screen.findByTestId('source-geofences-source')).toBeInTheDocument();
    expect(screen.getByTestId('layer-events-clusters')).toBeInTheDocument();
  });

  it('lets a click select a feature, and shows it in a popup', async () => {
    const onSelectionChange = vi.fn();
    render(<MapContainer api={api()} tenantId="wildlife-dept" onSelectionChange={onSelectionChange} />);
    loadMap();
    clickFeature({
      layerId: 'devices',
      featureId: deviceFeature.id,
      properties: deviceFeature.properties,
      geometry: deviceFeature.geometry,
    });
    await waitFor(() => {
      expect(screen.getByTestId('popup')).toBeInTheDocument();
    });
    expect(screen.getByRole('heading', { name: 'HB-CAM-01' })).toBeInTheDocument();
    expect(onSelectionChange).toHaveBeenCalledWith(
      expect.objectContaining({ layerId: 'devices', featureId: deviceFeature.id }),
    );
  });

  it('resolves the geographic context of a selected event without being asked', async () => {
    const client = api();
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    loadMap();
    clickFeature({
      layerId: 'events',
      featureId: eventFeature.id,
      properties: eventFeature.properties,
      geometry: eventFeature.geometry,
    });
    await waitFor(() => {
      expect(client.reverseGeocode).toHaveBeenCalled();
    });
    expect(await screen.findByText('North Central Province')).toBeInTheDocument();
  });

  it('clears the selection when the map is clicked where nothing is', async () => {
    const onSelectionChange = vi.fn();
    render(<MapContainer api={api()} onSelectionChange={onSelectionChange} />);
    loadMap();
    clickFeature({
      layerId: 'devices',
      featureId: deviceFeature.id,
      properties: deviceFeature.properties,
      geometry: deviceFeature.geometry,
    });
    await waitFor(() => {
      expect(screen.getByTestId('popup')).toBeInTheDocument();
    });
    act(() => {
      mapState.props?.onClick?.({ lngLat: { lng: 80.8, lat: 8.1 }, features: [] });
    });
    await waitFor(() => {
      expect(screen.queryByTestId('popup')).not.toBeInTheDocument();
    });
    expect(onSelectionChange).toHaveBeenLastCalledWith(null);
  });

  it('does not select what lies under the click that finished a drawing', async () => {
    render(<MapContainer api={api()} tenantId="wildlife-dept" />);
    loadMap();
    drawing.recentlyFinished = true;
    clickFeature({
      layerId: 'adminAreas',
      featureId: 'admin-1',
      properties: { name: 'Galoya' },
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByTestId('popup')).not.toBeInTheDocument();
  });

  it('only lets a click reach the layers that are on', async () => {
    render(<MapContainer api={api()} />);
    loadMap();
    await waitFor(() => {
      expect(mapState.props?.interactiveLayerIds).toBeDefined();
    });
    const ids = mapState.props?.interactiveLayerIds ?? [];
    expect(ids).toContain('devices-point');
    expect(ids).toContain('events-point');
    // The halo around each event marker is its larger click target.
    expect(ids).toContain('events-point-halo');
    expect(ids).not.toContain('facilities-point');
  });

  it('hands a click to the armed tool instead of the selection', async () => {
    const client = api();
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    loadMap();
    await userEvent.click(screen.getByRole('button', { name: 'Radius search' }));
    act(() => {
      mapState.props?.onClick?.({ lngLat: { lng: 80.75, lat: 8.03 }, features: [] });
    });
    await waitFor(() => {
      expect(client.queryWithinDistance).toHaveBeenCalledWith(
        expect.objectContaining({ geometry: { type: 'Point', coordinates: [80.75, 8.03] } }),
        expect.anything(),
      );
    });
    expect(screen.getByTestId('map')).toHaveAttribute('data-cursor', 'crosshair');
  });

  it('takes a failed layer off the status line when it is turned off', async () => {
    const client = apiStub({
      listFeatures: vi.fn(() => Promise.reject(new Error('gateway timeout'))),
      listEvents: vi.fn(() => Promise.resolve(eventCollection([]))),
    });
    render(<MapContainer api={client} />);
    loadMap();
    await screen.findAllByText(/did not load: gateway timeout/);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Devices' }));
    await waitFor(() => {
      const lines = screen.queryAllByText(/did not load/).map((line) => line.textContent);
      expect(lines.some((line) => line.includes('Devices'))).toBe(false);
    });
  });

  it('turns a layer off and stops drawing it', async () => {
    render(<MapContainer api={api()} />);
    loadMap();
    expect(await screen.findByTestId('source-devices-source')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Devices' }));
    await waitFor(() => {
      expect(screen.queryByTestId('source-devices-source')).not.toBeInTheDocument();
    });
  });

  it('opens the geofence editor, and loads the geofence that was selected', async () => {
    const client = api();
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    loadMap();
    await userEvent.click(await screen.findByRole('button', { name: 'New geofence' }));
    expect(screen.getByRole('heading', { name: 'Geofence editor' })).toBeInTheDocument();

    clickFeature({
      layerId: 'geofences',
      featureId: '0199f3d2-0000-0000-0000-00000000dd01',
      properties: { name: 'Habarana junction watch zone', status: 'active' },
      geometry: { type: 'Polygon', coordinates: [[[80.74, 8.02], [80.78, 8.02], [80.78, 8.05], [80.74, 8.02]]] },
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Edit this geofence' }));
    await waitFor(() => {
      expect(client.getGeofence).toHaveBeenCalledWith(
        '0199f3d2-0000-0000-0000-00000000dd01',
        expect.objectContaining({ tenantId: 'wildlife-dept' }),
      );
    });
    expect(await screen.findByDisplayValue('Habarana junction watch zone')).toBeInTheDocument();
  });

  it('does not put a geofence into the editor once the operator has moved on', async () => {
    // The answer arrives after the operator closed the editor and started a new geofence: saving must
    // create a new one, not replace the geofence that was asked for earlier.
    let answer: (value: Geofence) => void = () => undefined;
    const client = apiStub({
      listFeatures: vi.fn(() => Promise.resolve(featureCollection([]))),
      listEvents: vi.fn(() => Promise.resolve(eventCollection([]))),
      getGeofence: vi.fn(
        () =>
          new Promise<Geofence>((resolve) => {
            answer = resolve;
          }),
      ),
    });
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    loadMap();
    clickFeature({
      layerId: 'geofences',
      featureId: '0199f3d2-0000-0000-0000-00000000dd01',
      properties: { name: 'Habarana junction watch zone', status: 'active' },
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Edit this geofence' }));
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    await userEvent.click(screen.getByRole('button', { name: 'New geofence' }));
    await act(async () => {
      answer(geofence);
      await Promise.resolve();
    });
    expect(screen.getByLabelText('Name')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Create geofence' })).toBeInTheDocument();
  });

  it('does not say no basemap is configured when the operator chose none', async () => {
    render(
      <MapContainer
        api={api()}
        basemaps={[
          { id: 'osm', label: 'OpenStreetMap', styleUrl: 'https://tiles.example/style.json' },
          { id: 'neutral', label: 'No basemap', styleUrl: null },
        ]}
      />,
    );
    loadMap();
    await userEvent.selectOptions(await screen.findByLabelText('Basemap'), 'neutral');
    expect(screen.queryByText(/No basemap configured/)).not.toBeInTheDocument();
  });

  it('removes only the drawn filter area, not a geofence being edited', async () => {
    render(<MapContainer api={api()} tenantId="wildlife-dept" />);
    loadMap();
    await screen.findByRole('button', { name: 'New geofence' });
    const stub = drawing.stub;
    if (stub === null || drawing.options === null) {
      throw new Error('the container did not use Terra Draw');
    }
    const cleared = stub.calls.cleared;
    act(() => {
      drawing.options?.onFinish(
        {
          id: 'filter-1',
          geometry: { type: 'Polygon', coordinates: [[[80.7, 8.0], [80.8, 8.0], [80.8, 8.1], [80.7, 8.0]]] },
          properties: {},
        },
        'filter',
      );
    });
    expect(stub.calls.removed).toContain('filter-1');
    expect(stub.calls.cleared).toBe(cleared);
  });

  it('does not offer to edit a geofence when the editor is not rendered', async () => {
    render(<MapContainer api={api()} panels={['layers']} />);
    loadMap();
    clickFeature({
      layerId: 'geofences',
      featureId: 'gf-1',
      properties: { name: 'Watch zone' },
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
    });
    await waitFor(() => {
      expect(screen.getByTestId('popup')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: 'Edit this geofence' })).not.toBeInTheDocument();
  });

  it('says so when a geofence cannot be opened for editing', async () => {
    const client = apiStub({
      listFeatures: vi.fn(() => Promise.resolve(featureCollection([]))),
      listEvents: vi.fn(() => Promise.resolve(eventCollection([]))),
      getGeofence: vi.fn(() =>
        Promise.reject(
          new ApiError('not owner', {
            status: 403,
            problem: {
              type: 'urn:gis-core-service:problem:not_owner',
              title: 'Not the owner',
              status: 403,
              detail: 'The geofence belongs to another tenant.',
            },
          }),
        ),
      ),
    });
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    loadMap();
    clickFeature({
      layerId: 'geofences',
      featureId: 'gf-1',
      properties: { name: 'Watch zone' },
      geometry: { type: 'Point', coordinates: [80.75, 8.03] },
    });
    await userEvent.click(await screen.findByRole('button', { name: 'Edit this geofence' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('belongs to another tenant');
  });

  it('says when a layer could not be loaded', async () => {
    const client = apiStub({
      listFeatures: vi.fn(() => Promise.reject(new Error('gateway timeout'))),
      listEvents: vi.fn(() => Promise.resolve(eventCollection([]))),
    });
    render(<MapContainer api={client} />);
    loadMap();
    // Every visible feature layer failed, and each one is named: "nothing here" must not be mistaken
    // for "this did not load".
    const failures = await screen.findAllByText(/did not load: gateway timeout/);
    expect(failures.length).toBeGreaterThan(1);
    expect(failures.map((line) => line.textContent).join(' ')).toContain('Devices');
  });

  it('leaves out a layer the deployment does not publish', async () => {
    const client = apiStub({
      getLayerCatalogue: vi.fn(() =>
        Promise.resolve({ layers: [], refDataRelease: 'ref-2026.09-lka-open', attribution: [] }),
      ),
      listEvents: vi.fn(() => Promise.resolve(eventCollection([]))),
    });
    render(<MapContainer api={client} />);
    loadMap();
    await waitFor(() => {
      expect(screen.queryByRole('checkbox', { name: 'Devices' })).not.toBeInTheDocument();
    });
    // Events do not come from the layer registry, so they stay.
    expect(screen.getByRole('checkbox', { name: 'Events' })).toBeInTheDocument();
  });

  it('credits the sources of the reference data on the map', async () => {
    render(<MapContainer api={api()} tenantId="wildlife-dept" />);
    await waitFor(() => {
      expect(screen.getByTestId('attribution')).toHaveTextContent('© OpenStreetMap contributors');
    });
  });

  it('does not offer to export a layer whose licence does not allow it', async () => {
    const client = api();
    client.getLayerCatalogue.mockResolvedValue({
      ...layerCatalogue,
      layers: layerCatalogue.layers.map((layer) =>
        layer.code === 'ref.protected_area' ? { ...layer, exportable: false } : layer,
      ),
    });
    render(<MapContainer api={client} tenantId="wildlife-dept" />);
    loadMap();
    const choice = await screen.findByRole('combobox', { name: 'Layer' });
    await waitFor(() => {
      expect(within(choice).queryByRole('option', { name: 'Protected areas' })).not.toBeInTheDocument();
    });
    expect(within(choice).getByRole('option', { name: 'Roads' })).toBeInTheDocument();
  });
});
