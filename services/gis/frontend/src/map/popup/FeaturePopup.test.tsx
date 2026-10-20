import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('react-map-gl/maplibre', async () => (await import('../../test/reactMapGl')).mapGlMock());

import { deviceFeature, eventFeature, reverseGeocode } from '../../test/fixtures';
import type { Selection } from '../state/mapState';
import type { ReverseGeocodeState } from '../state/useReverseGeocode';
import { FeaturePopup } from './FeaturePopup';

const EVENT_SELECTION: Selection = {
  layerId: 'events',
  featureId: eventFeature.id,
  properties: eventFeature.properties,
  geometry: eventFeature.geometry,
  position: [80.749, 8.037],
};

const DEVICE_SELECTION: Selection = {
  layerId: 'devices',
  featureId: deviceFeature.id,
  properties: deviceFeature.properties,
  geometry: deviceFeature.geometry,
  position: [80.752, 8.04],
};

const NO_CONTEXT: ReverseGeocodeState = { status: 'idle', data: null, error: null };
const CONTEXT: ReverseGeocodeState = { status: 'success', data: reverseGeocode, error: null };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('FeaturePopup', () => {
  it('shows an event, its attributes and the codes its geo-context recorded', () => {
    render(
      <FeaturePopup
        selection={EVENT_SELECTION}
        context={NO_CONTEXT}
        onClose={vi.fn()}
        onRequestContext={vi.fn()}
      />,
    );
    expect(screen.getByRole('heading', { name: 'wildlife.elephant_detected' })).toBeInTheDocument();
    expect(screen.getByText('Events')).toBeInTheDocument();
    expect(screen.getByText('Event type')).toBeInTheDocument();
    expect(screen.getByText('Recorded codes: LK7 · LK71')).toBeInTheDocument();
    expect(screen.getByText('Source')).toBeInTheDocument();
  });

  it('resolves the position on request', async () => {
    const onRequestContext = vi.fn();
    render(
      <FeaturePopup
        selection={EVENT_SELECTION}
        context={NO_CONTEXT}
        onClose={vi.fn()}
        onRequestContext={onRequestContext}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Resolve this position' }));
    expect(onRequestContext).toHaveBeenCalled();
  });

  it('shows the geographic context once it has it', () => {
    render(
      <FeaturePopup
        selection={EVENT_SELECTION}
        context={CONTEXT}
        onClose={vi.fn()}
        onRequestContext={vi.fn()}
      />,
    );
    expect(screen.getByText('North Central Province')).toBeInTheDocument();
    expect(screen.getByText('Anuradhapura')).toBeInTheDocument();
    expect(screen.getByText(/Habarana · 512 m/)).toBeInTheDocument();
    expect(screen.getByText(/A11 · 49 m/)).toBeInTheDocument();
    // The event carries the release its geo-context used, and the reverse lookup names its own.
    expect(screen.getAllByText('ref-2026.09-lka-open')).toHaveLength(2);
    expect(screen.getByText('Release')).toBeInTheDocument();
  });

  it('says what state a device is reported to be in, and where that comes from', () => {
    render(
      <FeaturePopup
        selection={DEVICE_SELECTION}
        context={NO_CONTEXT}
        onClose={vi.fn()}
        onRequestContext={vi.fn()}
        deviceState={() => undefined}
      />,
    );
    expect(screen.getByText(/Reported state: Not reported/)).toBeInTheDocument();
    expect(screen.getByText(/device health comes from another service/)).toBeInTheDocument();
  });

  it('shows the state an external service reported', () => {
    render(
      <FeaturePopup
        selection={DEVICE_SELECTION}
        context={NO_CONTEXT}
        onClose={vi.fn()}
        onRequestContext={vi.fn()}
        deviceState={() => 'offline'}
      />,
    );
    expect(screen.getByText(/Reported state: Offline/)).toBeInTheDocument();
  });

  it('offers to edit a geofence that was selected', async () => {
    const onEditGeofence = vi.fn();
    render(
      <FeaturePopup
        selection={{ ...DEVICE_SELECTION, layerId: 'geofences', featureId: 'gf-1' }}
        context={NO_CONTEXT}
        onClose={vi.fn()}
        onRequestContext={vi.fn()}
        onEditGeofence={onEditGeofence}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Edit this geofence' }));
    expect(onEditGeofence).toHaveBeenCalledWith('gf-1');
  });

  it('shows what the service said when a position cannot be resolved', () => {
    render(
      <FeaturePopup
        selection={EVENT_SELECTION}
        context={{ status: 'error', data: null, error: 'The position is outside the service area.' }}
        onClose={vi.fn()}
        onRequestContext={vi.fn()}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('outside the service area');
  });
});
