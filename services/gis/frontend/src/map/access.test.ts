import { describe, expect, it } from 'vitest';

import { administrator, viewer } from '../test/fixtures';
import { abilitiesOf, UNKNOWN_ABILITIES } from './access';

describe('abilitiesOf', () => {
  it('offers an administrator everything the map can do', () => {
    expect(abilitiesOf(administrator)).toEqual({
      known: true,
      editGeofences: true,
      readEvents: true,
      askSpatialQuestions: true,
      exportData: true,
    });
  });

  it('offers a viewer the map only', () => {
    expect(abilitiesOf(viewer)).toEqual({
      known: true,
      editGeofences: false,
      readEvents: false,
      askSpatialQuestions: false,
      exportData: false,
    });
  });

  it('attempts reads but offers no change or export while the permissions are unknown', () => {
    expect(abilitiesOf(null)).toBe(UNKNOWN_ABILITIES);
    expect(UNKNOWN_ABILITIES).toMatchObject({ editGeofences: false, exportData: false, readEvents: true });
  });

  it('keeps working when the service reports a permission it does not know', () => {
    expect(abilitiesOf({ ...viewer, permissions: ['map:read', 'something:new'] }).known).toBe(true);
  });
});
