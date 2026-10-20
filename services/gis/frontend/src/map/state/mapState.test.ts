import { describe, expect, it } from 'vitest';

import {
  DRAWING_MODES,
  defaultEventFilters,
  eventWindow,
  isDrawing,
  MAX_EVENT_WINDOW_DAYS,
  WINDOW_PRESETS,
  windowHours,
  windowIsTooLong,
} from './mapState';

const NOW = new Date('2026-09-15T12:00:00Z');

describe('eventWindow', () => {
  it('reads back the last N hours when neither end is pinned', () => {
    const window = eventWindow(defaultEventFilters(24), NOW);
    expect(window.to).toBe('2026-09-15T12:00:00.000Z');
    expect(window.from).toBe('2026-09-14T12:00:00.000Z');
  });

  it('keeps a pinned window exactly as it was given', () => {
    const window = eventWindow(
      { ...defaultEventFilters(24), from: '2026-09-01T00:00:00Z', to: '2026-09-02T00:00:00Z' },
      NOW,
    );
    expect(window).toEqual({ from: '2026-09-01T00:00:00Z', to: '2026-09-02T00:00:00Z' });
  });

  it('measures back from a pinned end', () => {
    const window = eventWindow({ ...defaultEventFilters(6), to: '2026-09-10T06:00:00Z' }, NOW);
    expect(window.from).toBe('2026-09-10T00:00:00.000Z');
  });

  it('measures its own width', () => {
    expect(windowHours({ from: '2026-09-14T12:00:00Z', to: '2026-09-15T12:00:00Z' })).toBe(24);
  });

  it('knows when a window is longer than the service allows', () => {
    expect(windowIsTooLong({ from: '2026-08-01T00:00:00Z', to: '2026-09-15T00:00:00Z' })).toBe(true);
    expect(windowIsTooLong(eventWindow(defaultEventFilters(MAX_EVENT_WINDOW_DAYS * 24), NOW))).toBe(false);
  });

  it('offers only presets the service accepts', () => {
    for (const preset of WINDOW_PRESETS) {
      expect(preset.hours).toBeLessThanOrEqual(MAX_EVENT_WINDOW_DAYS * 24);
    }
  });
});

describe('interaction modes', () => {
  it('knows which modes hand the pointer to Terra Draw', () => {
    expect(DRAWING_MODES).toEqual(['drawFilter', 'drawGeofence']);
    expect(isDrawing('drawGeofence')).toBe(true);
    expect(isDrawing('select')).toBe(false);
    expect(isDrawing('measure')).toBe(false);
  });
});
