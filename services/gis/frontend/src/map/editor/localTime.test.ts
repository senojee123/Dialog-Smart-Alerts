import { describe, expect, it } from 'vitest';

import { fromLocalInput, toLocalInput } from './localTime';

describe('local time inputs', () => {
  it('round-trips an instant through the input format', () => {
    const iso = '2026-09-15T12:34:00.000Z';
    const local = toLocalInput(iso);
    expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(fromLocalInput(local)).toBe(iso);
  });

  it('treats nothing as nothing', () => {
    expect(toLocalInput(null)).toBe('');
    expect(fromLocalInput('')).toBeNull();
  });

  it('ignores what is not a time', () => {
    expect(toLocalInput('not a time')).toBe('');
    expect(fromLocalInput('not a time')).toBeNull();
  });
});
