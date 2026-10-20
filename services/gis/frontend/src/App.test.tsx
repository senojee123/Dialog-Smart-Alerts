import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./map/MapContainer', () => ({
  MapContainer: () => <div data-testid="map-client" />,
}));

const stubs = vi.hoisted(() => ({ getReadiness: vi.fn(), getServiceArea: vi.fn() }));
vi.mock('./services/gisApi', () => ({ gisApi: stubs }));

import { App } from './App';
import { readyReport, serviceArea } from './test/fixtures';

describe('App', () => {
  beforeEach(() => {
    stubs.getReadiness.mockResolvedValue(readyReport);
    stubs.getServiceArea.mockResolvedValue(serviceArea);
  });

  it('embeds the map client under a header', async () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: 'GIS Core Service' })).toBeInTheDocument();
    expect(screen.getByTestId('map-client')).toBeInTheDocument();
    await waitFor(() => {
      expect(stubs.getServiceArea).toHaveBeenCalled();
    });
  });

  it('shows the service status when asked, and says it is ready', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Service ready' })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Service ready' }));
    expect(screen.getByRole('heading', { name: 'Service status' })).toBeInTheDocument();
    expect(screen.getByText('PostgreSQL 18.6')).toBeInTheDocument();
  });
});
