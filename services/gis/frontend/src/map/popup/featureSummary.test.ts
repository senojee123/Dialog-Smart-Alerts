import { describe, expect, it } from 'vitest';

import { deviceFeature, eventFeature, settlementFeature } from '../../test/fixtures';
import { adminCodesOf, formatValue, isEventLayer, labelFor, summaryRows, titleOf } from './featureSummary';

describe('labelFor', () => {
  it('uses the label it knows', () => {
    expect(labelFor('settlementType')).toBe('Settlement type');
    expect(labelFor('refCode')).toBe('Route number');
  });

  it('makes words out of a property it has never seen', () => {
    expect(labelFor('someNewAttribute')).toBe('Some New Attribute');
  });
});

describe('formatValue', () => {
  it('shows metres, areas and angles in their units', () => {
    expect(formatValue('distanceM', 512.34)).toBe('512 m');
    expect(formatValue('radiusM', 2500)).toBe('2.50 km');
    expect(formatValue('areaM2', 1_767_145)).toBe('1.77 km²');
    expect(formatValue('bearingDeg', 225)).toBe('225°');
  });

  it('leaves nothing for nothing', () => {
    expect(formatValue('name', null)).toBeNull();
    expect(formatValue('name', undefined)).toBeNull();
    expect(formatValue('name', '')).toBeNull();
  });

  it('formats an instant and leaves other text alone', () => {
    expect(formatValue('observedAt', '2026-09-14T03:02:10Z')).toMatch(/2026/);
    expect(formatValue('name', 'Habarana')).toBe('Habarana');
    expect(formatValue('observedAt', 'not a time')).toBe('not a time');
  });

  it('handles booleans, numbers, lists and objects', () => {
    expect(formatValue('onBoundary', true)).toBe('yes');
    expect(formatValue('population', 4200)).toBe('4,200');
    expect(formatValue('sharedWithTenants', ['a', 'b'])).toBe('a, b');
    expect(formatValue('attributes', { team: 'north' })).toBe('{"team":"north"}');
  });
});

describe('summaryRows', () => {
  it('leaves out the properties the client added and the ones shown elsewhere', () => {
    const rows = summaryRows({
      ...eventFeature.properties,
      _featureId: 'x',
      _layerId: 'events',
      _deviceState: 'online',
    });
    const keys = rows.map((row) => row.key);
    expect(keys).not.toContain('_featureId');
    expect(keys).not.toContain('_layerId');
    expect(keys).not.toContain('_deviceState');
    expect(keys).not.toContain('admin');
    expect(keys).not.toContain('eventId');
    expect(keys).toContain('eventType');
  });

  it('labels every row it shows', () => {
    for (const row of summaryRows(settlementFeature.properties)) {
      expect(row.label).not.toBe('');
      expect(row.value).not.toBe('');
    }
  });
});

describe('titleOf', () => {
  it('prefers the name', () => {
    expect(titleOf('settlements', settlementFeature.properties, settlementFeature.id)).toBe('Habarana');
    expect(titleOf('devices', deviceFeature.properties, deviceFeature.id)).toBe('HB-CAM-01');
  });

  it('falls back to the event type, then to the id', () => {
    expect(titleOf('events', eventFeature.properties, eventFeature.id)).toBe(
      'wildlife.elephant_detected',
    );
    expect(titleOf('settlements', {}, 'abc-123')).toBe('abc-123');
  });

  it('names a field of view by its device', () => {
    expect(titleOf('deviceFieldOfView', { deviceId: '0199f3d2-aaaa' }, 'fov-1')).toBe(
      'Field of view of 0199f3d2',
    );
  });
});

describe('adminCodesOf', () => {
  it('reads the codes the geo-context of an event recorded', () => {
    expect(adminCodesOf(eventFeature.properties)).toEqual({ l1: 'LK7', l2: 'LK71', l3: null, l4: null });
  });

  it('has nothing for a feature without them', () => {
    expect(adminCodesOf(settlementFeature.properties)).toBeNull();
    expect(adminCodesOf({ admin: { l1: null, l2: null, l3: null, l4: null } })).toBeNull();
  });

  it('knows the event layer', () => {
    expect(isEventLayer('events')).toBe(true);
    expect(isEventLayer('devices')).toBe(false);
  });
});
