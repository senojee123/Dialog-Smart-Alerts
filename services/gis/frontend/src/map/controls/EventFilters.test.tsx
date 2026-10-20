import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { defaultEventFilters, type EventFilterState } from '../state/mapState';
import { EventFilters } from './EventFilters';

function renderFilters(filters: EventFilterState = defaultEventFilters(24), disabled = false) {
  const onChange = vi.fn();
  const onRefresh = vi.fn();
  render(
    <EventFilters
      filters={filters}
      onChange={onChange}
      knownEventTypes={['wildlife.elephant_detected', 'security.intrusion']}
      knownSourceTypes={['sensor']}
      answeredWindow={{ from: '2026-09-14T00:00:00Z', to: '2026-09-15T00:00:00Z' }}
      count={12}
      truncated={false}
      loadedAt={new Date('2026-09-15T12:00:00Z')}
      onRefresh={onRefresh}
      disabled={disabled}
    />,
  );
  return { onChange, onRefresh };
}

describe('EventFilters', () => {
  it('is named for what it does, so it is not confused with the layer', () => {
    renderFilters();
    expect(screen.getByRole('heading', { name: 'Event filters' })).toBeInTheDocument();
  });

  it('offers the windows the service accepts and marks the one in use', () => {
    renderFilters();
    expect(screen.getByRole('button', { name: '24 h' })).toHaveAttribute('class', expect.stringContaining('active'));
    expect(screen.getByRole('button', { name: '31 d' })).toBeInTheDocument();
    expect(screen.getByText(/longer than 31 days is refused/)).toBeInTheDocument();
  });

  it('changes the window to a preset, clearing any pinned ends', async () => {
    const { onChange } = renderFilters({ ...defaultEventFilters(24), from: '2026-09-01T00:00:00Z' });
    await userEvent.click(screen.getByRole('button', { name: '6 h' }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ windowHours: 6, from: null, to: null }),
    );
  });

  it('shows the window the service answered for, not the one that was asked for', () => {
    renderFilters();
    expect(screen.getByText('Window answered')).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('filters by event type, choosing one of the known types as a whole', async () => {
    const { onChange } = renderFilters();
    const select = screen.getByLabelText('Event type');
    const options = [...select.querySelectorAll('option')].map((option) => option.getAttribute('value'));
    expect(options).toEqual(['', 'wildlife.elephant_detected', 'security.intrusion']);
    await userEvent.selectOptions(select, 'security.intrusion');
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ eventType: 'security.intrusion' }));
  });

  it('goes back to any event type', async () => {
    const { onChange } = renderFilters({ ...defaultEventFilters(24), eventType: 'security.intrusion' });
    const select = screen.getByLabelText('Event type');
    expect(select).toHaveValue('security.intrusion');
    await userEvent.selectOptions(select, 'any');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ eventType: null }));
  });

  it('keeps the type in force selectable when no loaded event has it', () => {
    renderFilters({ ...defaultEventFilters(24), eventType: 'fire.smoke_detected' });
    expect(screen.getByLabelText('Event type')).toHaveValue('fire.smoke_detected');
  });

  it('filters by source', async () => {
    const { onChange } = renderFilters();
    await userEvent.selectOptions(screen.getByLabelText('Source'), 'sensor');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ sourceType: 'sensor' }));
  });

  it('offers a way back to the relative window once one is pinned', async () => {
    const { onChange } = renderFilters({ ...defaultEventFilters(6), from: '2026-09-01T00:00:00Z' });
    await userEvent.click(screen.getByRole('button', { name: 'Back to the last 6 h' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ from: null, to: null }));
  });

  it('says when the event layer is off', () => {
    renderFilters(defaultEventFilters(24), true);
    expect(screen.getByText('Turn the event layer on to load events.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeDisabled();
  });
});

describe('EventFilters, when a window the service would refuse is pinned', () => {
  it('says so before the request is made', () => {
    render(
      <EventFilters
        filters={{
          eventType: null,
          sourceType: null,
          windowHours: 24,
          from: '2026-01-01T00:00:00Z',
          to: '2026-09-15T00:00:00Z',
        }}
        onChange={vi.fn()}
        knownEventTypes={[]}
        knownSourceTypes={[]}
        answeredWindow={null}
        count={0}
        truncated={false}
        loadedAt={null}
        onRefresh={vi.fn()}
        disabled={false}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('longer than 31 days');
  });
});
