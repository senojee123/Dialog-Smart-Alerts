import { StrictMode, type ReactElement } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '../../services/apiClient';
import { apiStub } from '../../test/apiStub';
import { drawStub } from '../../test/drawStub';
import { geofence, polygonGeofence } from '../../test/fixtures';
import { fromWebMercator, toWebMercator } from '../../geo/geometry';
import type { Position } from '../../geo/sld99';
import type { Geometry } from '../../types/api';
import { GeofenceEditor, type GeofenceDrawHandlers } from './GeofenceEditor';
import type { TerraDrawController } from './useTerraDraw';

const SERVICE_AREA = [79.44, 5.66, 82.15, 10.08] as const;
const CENTRE: Position = [80.7487, 8.0356];

function drawnCircle(radiusMercator = 1200): Geometry {
  const [cx, cy] = toWebMercator(CENTRE);
  const ring: Position[] = [];
  for (let index = 0; index < 64; index += 1) {
    const angle = (2 * Math.PI * index) / 64;
    ring.push(fromWebMercator([cx + radiusMercator * Math.cos(angle), cy + radiusMercator * Math.sin(angle)]));
  }
  ring.push(ring[0] as Position);
  return { type: 'Polygon', coordinates: [ring] };
}

const DRAWN_POLYGON: Geometry = {
  type: 'Polygon',
  coordinates: [
    [
      [80.74, 8.02],
      [80.78, 8.02],
      [80.78, 8.05],
      [80.74, 8.05],
      [80.74, 8.02],
    ],
  ],
};

function setUp(
  options: {
    api?: ReturnType<typeof apiStub>;
    editing?: typeof geofence | null;
    draw?: ReturnType<typeof drawStub>;
    /** Mount in React's strict mode, which runs every effect twice as the development build does. */
    strict?: boolean;
  } = {},
) {
  const api = options.api ?? apiStub();
  const draw = options.draw ?? drawStub();
  const onSaved = vi.fn();
  const onClose = vi.fn();
  const onDraftChange = vi.fn();
  let handlers: GeofenceDrawHandlers | null = null;
  // Terra Draw reports every shape it removes, also on a clear, as a deletion.
  draw.onRemove = (id) => {
    handlers?.onChange(id, null);
  };
  const editor = (controller: TerraDrawController) => (
    <GeofenceEditor
      api={api}
      draw={controller}
      registerDrawHandlers={(next) => {
        handlers = next;
      }}
      tenantId="wildlife-dept"
      serviceAreaBounds={SERVICE_AREA}
      initialGeofence={options.editing ?? null}
      onDraftChange={onDraftChange}
      onSaved={onSaved}
      onClose={onClose}
    />
  );
  const wrap = (element: ReactElement) =>
    options.strict === true ? <StrictMode>{element}</StrictMode> : element;
  const view = render(wrap(editor(draw)));
  return {
    api,
    draw,
    onSaved,
    onClose,
    onDraftChange,
    finish: (geometry: Geometry, id = 'drawn-1') => {
      if (handlers === null) {
        throw new Error('the editor did not register its draw handlers');
      }
      handlers.onFinish({ id, geometry, properties: {} });
    },
    change: (geometry: Geometry | null, id = 'drawn-1') => {
      if (handlers === null) {
        throw new Error('the editor did not register its draw handlers');
      }
      handlers.onChange(id, geometry === null ? null : { id, geometry, properties: {} });
    },
    /** Render again with another state of the controller (Terra Draw stopping and starting again). */
    rerenderWith: (controller: TerraDrawController) => {
      view.rerender(wrap(editor(controller)));
    },
  };
}

describe('GeofenceEditor', () => {
  it('offers the three shapes the service stores, and arms Terra Draw for the one chosen', async () => {
    const { draw } = setUp();
    expect(screen.getByRole('button', { name: 'Polygon' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Circle' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Corridor' }));
    expect(draw.calls.modes).toContainEqual(['corridor', 'geofence']);
  });

  it('tells the operator how to draw the shape being drawn', () => {
    // The draft starts as a polygon, so the polygon hint is the one showing while polygon mode is armed.
    setUp({ draw: drawStub({ mode: 'polygon' }) });
    expect(screen.getByText(/Click each corner/)).toBeInTheDocument();
  });

  it('will not save until there is a name and a shape', async () => {
    const { api } = setUp();
    expect(screen.getByRole('button', { name: 'Create geofence' })).toBeDisabled();
    expect(screen.getByText('A geofence needs a name.')).toBeInTheDocument();
    expect(screen.getByText('Draw the geofence on the map.')).toBeInTheDocument();
    expect(api.createGeofence).not.toHaveBeenCalled();
  });

  it('turns a drawn circle into a centre and a radius, and keeps the ring out of the way', async () => {
    const { draw, finish, change } = setUp();
    // Terra Draw reports removing the drawn ring as a deletion; that must not discard the circle.
    draw.onRemove = (id) => {
      change(null, id);
    };
    await userEvent.click(screen.getByRole('button', { name: 'Circle' }));
    finish(drawnCircle());
    await waitFor(() => {
      const value = Number((screen.getByLabelText('Radius (m)') as HTMLInputElement).value);
      expect(value).toBeGreaterThan(1150);
      expect(value).toBeLessThan(1200);
    });
    // The drawn ring has served its purpose: the map draws the exact circle from the definition.
    expect(draw.calls.removed).toEqual(['drawn-1']);
    expect(draw.calls.modes).toContainEqual(['static', 'geofence']);
    // ... and the circle is still the draft's shape.
    expect(screen.queryByText('Draw the geofence on the map.')).not.toBeInTheDocument();
  });

  it('keeps a drawn polygon in Terra Draw so its corners can be moved', async () => {
    const { draw, finish, change, onDraftChange } = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Polygon' }));
    finish(DRAWN_POLYGON);
    await waitFor(() => {
      expect(draw.calls.modes).toContainEqual(['select', 'geofence']);
    });
    expect(draw.calls.removed).toEqual([]);
    const moved: Geometry = {
      type: 'Polygon',
      coordinates: [
        [
          [80.74, 8.02],
          [80.79, 8.02],
          [80.79, 8.06],
          [80.74, 8.06],
          [80.74, 8.02],
        ],
      ],
    };
    change(moved);
    await waitFor(() => {
      expect(onDraftChange).toHaveBeenCalledWith(expect.objectContaining({ geometry: moved }));
    });
  });

  it('forgets the shape when the operator deletes it in Terra Draw', async () => {
    const { finish, change, onDraftChange } = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Polygon' }));
    finish(DRAWN_POLYGON);
    change(null);
    await waitFor(() => {
      expect(onDraftChange).toHaveBeenCalledWith(expect.objectContaining({ geometry: null }));
    });
  });

  it('keeps the shape when Terra Draw removes the handles of a deselected shape', async () => {
    // Deselecting (a click on the empty map, Escape) deletes the corner handles select mode added; those
    // are other features than the shape, and the draft must keep its geometry.
    const { finish, change } = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Polygon' }));
    finish(DRAWN_POLYGON);
    change(null, 'selection-point-1');
    change(null, 'midpoint-2');
    await userEvent.type(screen.getByLabelText('Name'), 'Tank bund');
    expect(screen.queryByText('Draw the geofence on the map.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create geofence' })).toBeEnabled();
  });

  it('does not take a shape that is still being drawn as the draft', async () => {
    // Terra Draw updates the unfinished polygon as the pointer moves; Escape then discards it. Until it
    // is finished it is not the geofence.
    const { change } = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Polygon' }));
    change(DRAWN_POLYGON, 'drawing-7');
    change(null, 'drawing-7');
    await userEvent.type(screen.getByLabelText('Name'), 'Half drawn');
    expect(screen.getByText('Draw the geofence on the map.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create geofence' })).toBeDisabled();
  });

  it('keeps the geometry of a geofence it opens when its effects run twice', () => {
    // React's development build runs effects twice; the second run clears what the first loaded, and
    // Terra Draw reports that as a deletion.
    const { draw } = setUp({ editing: polygonGeofence, strict: true });
    expect(draw.calls.loaded.length).toBeGreaterThanOrEqual(2);
    expect(draw.held.size).toBe(1);
    expect(screen.queryByText('Draw the geofence on the map.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save version 4' })).toBeEnabled();
  });

  it('hands the shape as edited to a Terra Draw that starts again', async () => {
    // A new basemap replaces Terra Draw's instance: the editor gives the new one the draft as it is now,
    // not the geometry it was opened with.
    const draw = drawStub();
    const { change, rerenderWith } = setUp({ draw, editing: polygonGeofence });
    const moved: Geometry = {
      type: 'Polygon',
      coordinates: [
        [
          [80.74, 8.02],
          [80.8, 8.02],
          [80.8, 8.07],
          [80.74, 8.07],
          [80.74, 8.02],
        ],
      ],
    };
    change(moved);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Save version 4' })).toBeEnabled();
    });
    rerenderWith({ ...draw, ready: false });
    rerenderWith({ ...draw, ready: true });
    expect(draw.calls.loaded.at(-1)).toEqual(moved);
    expect(screen.queryByText('Draw the geofence on the map.')).not.toBeInTheDocument();
  });

  it('creates a geofence from the definition that was drawn', async () => {
    const { api, finish, onSaved } = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Circle' }));
    finish(drawnCircle());
    await userEvent.type(screen.getByLabelText('Name'), 'Habarana junction watch zone');
    await userEvent.clear(screen.getByLabelText('Radius (m)'));
    await userEvent.type(screen.getByLabelText('Radius (m)'), '750');
    await userEvent.click(screen.getByRole('button', { name: 'Create geofence' }));
    await waitFor(() => {
      expect(api.createGeofence).toHaveBeenCalled();
    });
    const [body, options] = api.createGeofence.mock.calls[0] as [Record<string, unknown>, { tenantId: string }];
    expect(body).toMatchObject({
      name: 'Habarana junction watch zone',
      definition: { kind: 'circle', radiusM: 750 },
      status: 'active',
      sharingPolicy: 'private',
    });
    expect(options.tenantId).toBe('wildlife-dept');
    expect(onSaved).toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('Saved as version 1.');
  });

  it('refuses a radius the service would refuse', async () => {
    const { api, finish } = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Circle' }));
    finish(drawnCircle());
    await userEvent.type(screen.getByLabelText('Name'), 'Too big');
    await userEvent.clear(screen.getByLabelText('Radius (m)'));
    await userEvent.type(screen.getByLabelText('Radius (m)'), '50001');
    expect(screen.getByText(/must be 50,000 m or less/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create geofence' })).toBeDisabled();
    expect(api.createGeofence).not.toHaveBeenCalled();
  });

  it('loads a geofence it was given, and replaces it at the version it read', async () => {
    const api = apiStub();
    const { draw } = setUp({ api, editing: polygonGeofence });
    expect(screen.getByLabelText('Name')).toHaveValue('Elephant corridor watch');
    expect(draw.calls.loaded[0]).toEqual(polygonGeofence.definition.geometry);
    expect(screen.getByRole('button', { name: 'Save version 4' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Save version 4' }));
    await waitFor(() => {
      expect(api.replaceGeofence).toHaveBeenCalled();
    });
    const [id, body] = api.replaceGeofence.mock.calls[0] as [string, { version: number }];
    expect(id).toBe(polygonGeofence.id);
    expect(body.version).toBe(3);
  });

  it('does not hand a circle to Terra Draw, because its definition is not a ring', () => {
    const { draw } = setUp({ editing: geofence });
    expect(draw.calls.loaded).toEqual([]);
    expect(draw.calls.modes).toContainEqual(['static', 'geofence']);
  });

  it('shows what the service said when the geofence has moved on', async () => {
    const api = apiStub({
      replaceGeofence: vi.fn(() =>
        Promise.reject(
          new ApiError('conflict', {
            status: 409,
            problem: {
              type: 'urn:gis-core-service:problem:version_conflict',
              title: 'Version conflict',
              status: 409,
              detail: 'The geofence has changed since it was read.',
              currentVersion: 7,
            },
          }),
        ),
      ),
    });
    setUp({ api, editing: polygonGeofence });
    await userEvent.click(screen.getByRole('button', { name: 'Save version 4' }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('The geofence has changed since it was read.');
    });
    expect(screen.getByRole('alert')).toHaveTextContent('now at version 7');
    expect(screen.getByRole('alert')).toHaveTextContent('version_conflict');
  });

  it('archives a geofence, and can delete it irreversibly', async () => {
    const api = apiStub();
    setUp({ api, editing: polygonGeofence });
    await userEvent.click(screen.getByRole('button', { name: 'Archive' }));
    await waitFor(() => {
      expect(api.deleteGeofence).toHaveBeenCalledWith(
        polygonGeofence.id,
        expect.objectContaining({ purge: false, version: 3 }),
      );
    });
  });

  it('asks for the tenants a shared geofence is shared with', async () => {
    setUp();
    await userEvent.selectOptions(screen.getByLabelText('Sharing'), 'shared');
    await userEvent.type(screen.getByLabelText('Shared with tenants'), 'forest-dept, police');
    expect(screen.getByLabelText('Shared with tenants')).toHaveValue('forest-dept, police');
  });

  it('clears the shape and starts again', async () => {
    const { draw, finish } = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Polygon' }));
    finish(DRAWN_POLYGON);
    await userEvent.click(screen.getByRole('button', { name: 'Clear shape' }));
    expect(screen.getByText('Draw the geofence on the map.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'New' }));
    expect(draw.calls.cleared).toBeGreaterThan(1);
  });

  it('closes when it is asked to', async () => {
    const { onClose } = setUp();
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();
  });
});
