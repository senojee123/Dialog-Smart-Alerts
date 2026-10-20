import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ResourceState } from '../hooks/useApiResource';
import { readyReport, serviceArea } from '../test/fixtures';
import type { Readiness, ServiceArea } from '../types/api';
import { StatusPanel } from './StatusPanel';

const areaLoaded: ResourceState<ServiceArea> = { status: 'success', data: serviceArea, error: null };

describe('StatusPanel', () => {
  it('shows each readiness check with a readable summary', () => {
    const readiness: ResourceState<Readiness> = { status: 'success', data: readyReport, error: null };
    render(<StatusPanel readiness={readiness} serviceArea={areaLoaded} onRefresh={vi.fn()} />);

    expect(screen.getByRole('status')).toHaveTextContent('Ready');
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(5);
    const [, postgisItem, , crsItem] = items;
    if (postgisItem === undefined || crsItem === undefined) {
      throw new Error('expected one list item per readiness check');
    }
    expect(within(postgisItem).getByText('PostGIS 3.6.4')).toBeInTheDocument();
    expect(within(crsItem).getByText('Warning')).toBeInTheDocument();
    expect(screen.getByText('database and application disagree')).toBeInTheDocument();
    expect(screen.getByText('79.44, 5.66, 82.15, 10.08')).toBeInTheDocument();
  });

  it('keeps the last report visible and explains when the API is unreachable', () => {
    const readiness: ResourceState<Readiness> = { status: 'error', data: null, error: new Error('Request to /health/ready failed: network error') };
    render(<StatusPanel readiness={readiness} serviceArea={areaLoaded} onRefresh={vi.fn()} />);
    expect(screen.getByRole('status')).toHaveTextContent('API unreachable');
    expect(screen.getByText(/network error/)).toBeInTheDocument();
  });

  it('calls onRefresh', async () => {
    const onRefresh = vi.fn();
    const readiness: ResourceState<Readiness> = { status: 'loading', data: null, error: null };
    render(<StatusPanel readiness={readiness} serviceArea={areaLoaded} onRefresh={onRefresh} />);
    expect(screen.getByRole('status')).toHaveTextContent('Checking');
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });
});
