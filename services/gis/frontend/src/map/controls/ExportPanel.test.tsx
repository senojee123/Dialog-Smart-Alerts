import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../services/apiClient';
import { apiStub } from '../../test/apiStub';
import { emptyFeatureCollection } from '../../test/fixtures';
import { MAP_LAYERS } from '../layers/layerCatalogue';
import { exportFilename } from './download';
import { ExportPanel } from './ExportPanel';

const VIEW = [80.7, 7.9, 80.8, 8.1] as const;
const EXPORTED_AT = '2026-09-23T10:15:00.123456Z';

describe('ExportPanel', () => {
  it('exports the chosen layer in the current view and saves it as a file', async () => {
    const client = apiStub({
      exportFeatures: vi.fn(() =>
        Promise.resolve({
          ...emptyFeatureCollection,
          count: 3,
          exportedAt: EXPORTED_AT,
          tenantId: 'wildlife-dept',
          attribution: [],
        }),
      ),
    });
    const save = vi.fn();
    render(
      <ExportPanel
        api={client}
        tenantId="wildlife-dept"
        layers={MAP_LAYERS}
        bounds={VIEW}
        events={null}
        save={save}
      />,
    );
    const geofences = MAP_LAYERS.find((layer) => layer.apiLayer === 'ops.geofence');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Layer' }), geofences?.id ?? '');
    await userEvent.click(screen.getByRole('button', { name: 'Export view' }));

    await waitFor(() => {
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({ count: 3 }),
        'ops-geofence-20260923T101500Z.geojson',
      );
    });
    expect(client.exportFeatures).toHaveBeenCalledWith({
      layer: 'ops.geofence',
      bounds: VIEW,
      tenantId: 'wildlife-dept',
    });
    expect(screen.getByRole('status')).toHaveTextContent('3 features exported');
    expect(screen.getByText(/recorded in the service.s audit log/)).toBeInTheDocument();
  });

  it('resolves the event selection only when an export is asked for', async () => {
    const client = apiStub({
      exportEvents: vi.fn(() =>
        Promise.resolve({
          ...emptyFeatureCollection,
          exportedAt: EXPORTED_AT,
          attribution: [],
          window: { from: '2026-09-22T10:00:00Z', to: '2026-09-23T10:00:00Z' },
        }),
      ),
    });
    const selection = {
      from: '2026-09-22T10:00:00Z',
      to: '2026-09-23T10:00:00Z',
      tenantId: 'wildlife-dept',
    };
    const events = vi.fn(() => selection);
    render(
      <ExportPanel
        api={client}
        tenantId="wildlife-dept"
        layers={[]}
        bounds={VIEW}
        events={events}
        save={vi.fn()}
      />,
    );

    expect(events).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Export events of the window' }));

    await waitFor(() => {
      expect(client.exportEvents).toHaveBeenCalledWith(selection);
    });
  });

  it('asks for the attribution the sources of exported reference data require', async () => {
    const client = apiStub({
      exportFeatures: vi.fn(() =>
        Promise.resolve({
          ...emptyFeatureCollection,
          count: 12,
          exportedAt: EXPORTED_AT,
          attribution: ['© OpenStreetMap contributors'],
        }),
      ),
    });
    render(
      <ExportPanel
        api={client}
        tenantId={null}
        layers={MAP_LAYERS}
        bounds={VIEW}
        events={null}
        save={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Export view' }));

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Keep the attribution with the data: © OpenStreetMap contributors.',
    );
  });

  it('says when the licence of reference data does not allow its export', async () => {
    const client = apiStub({
      exportFeatures: vi.fn(() =>
        Promise.reject(
          new ApiError('not permitted', {
            status: 403,
            problem: {
              type: 'urn:gis-core-service:problem:export_not_permitted',
              title: 'The licence of this data does not permit exports',
              status: 403,
              detail: 'the licence of wdpa does not allow ref.protected_area to leave the platform',
            },
          }),
        ),
      ),
    });
    const save = vi.fn();
    render(
      <ExportPanel
        api={client}
        tenantId={null}
        layers={MAP_LAYERS}
        bounds={VIEW}
        events={null}
        save={save}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Export view' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('does not allow ref.protected_area to leave the platform');
    expect(save).not.toHaveBeenCalled();
  });

  it('says why an export was refused, and saves nothing', async () => {
    const client = apiStub({
      exportFeatures: vi.fn(() =>
        Promise.reject(
          new ApiError('too large', {
            status: 422,
            problem: {
              type: 'urn:gis-core-service:problem:export_too_large',
              title: 'Export is larger than allowed',
              status: 422,
              detail: 'the selection holds more than 10000 features; narrow the area',
            },
          }),
        ),
      ),
    });
    const save = vi.fn();
    render(
      <ExportPanel
        api={client}
        tenantId={null}
        layers={MAP_LAYERS}
        bounds={VIEW}
        events={null}
        save={save}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Export view' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('narrow the area');
    expect(save).not.toHaveBeenCalled();
  });

  it('waits for a view before exporting one', () => {
    render(
      <ExportPanel api={apiStub()} tenantId={null} layers={MAP_LAYERS} bounds={null} events={null} />,
    );
    expect(screen.getByRole('button', { name: 'Export view' })).toBeDisabled();
  });
});

describe('exportFilename', () => {
  it('names the file after what was exported and when', () => {
    expect(exportFilename('ops.site', '2026-09-23T10:15:00+00:00')).toBe(
      'ops-site-20260923T101500Z.geojson',
    );
    expect(exportFilename('events', 'not a time')).toBe('events.geojson');
  });
});
