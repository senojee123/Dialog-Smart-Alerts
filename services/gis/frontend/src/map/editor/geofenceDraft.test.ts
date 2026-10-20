import { describe, expect, it } from 'vitest';

import { meanRadiusM, toWebMercator, fromWebMercator, webMercatorCentre, type Bounds } from '../../geo/geometry';
import { distanceM, type Position } from '../../geo/sld99';
import { geofence, polygonGeofence } from '../../test/fixtures';
import type { Geometry } from '../../types/api';
import {
  definitionFromDrawn,
  describeDraft,
  draftAreaM2,
  draftFromGeofence,
  draftIsValid,
  draftShape,
  draftToInput,
  emptyDraft,
  formatArea,
  formatMetres,
  MAX_CIRCLE_RADIUS_M,
  MAX_CORRIDOR_HALF_WIDTH_M,
  validateDraft,
  type GeofenceDraft,
} from './geofenceDraft';

const SERVICE_AREA: Bounds = [79.44, 5.66, 82.15, 10.08];
const CENTRE: Position = [80.7487, 8.0356];

const SQUARE: Geometry = {
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

function drawnCircle(radiusMercator: number, steps = 64): Geometry {
  const [cx, cy] = toWebMercator(CENTRE);
  const ring: Position[] = [];
  for (let index = 0; index < steps; index += 1) {
    const angle = (2 * Math.PI * index) / steps;
    ring.push(fromWebMercator([cx + radiusMercator * Math.cos(angle), cy + radiusMercator * Math.sin(angle)]));
  }
  const first = ring[0];
  if (first === undefined) {
    throw new Error('the ring is empty');
  }
  ring.push(first);
  return { type: 'Polygon', coordinates: [ring] };
}

function named(draft: GeofenceDraft): GeofenceDraft {
  return { ...draft, name: 'Watch zone' };
}

describe('emptyDraft', () => {
  it('starts a polygon without a radius and a circle with one', () => {
    expect(emptyDraft('polygon').radiusM).toBeNull();
    expect(emptyDraft('circle').radiusM).toBe(500);
    expect(emptyDraft('corridor').radiusM).toBe(50);
    expect(emptyDraft('polygon').status).toBe('active');
    expect(emptyDraft('polygon').sharingPolicy).toBe('private');
  });
});

describe('draftFromGeofence', () => {
  it('loads the definition, the version and the sharing as they were read', () => {
    const draft = draftFromGeofence(geofence);
    expect(draft.id).toBe(geofence.id);
    expect(draft.version).toBe(1);
    expect(draft.kind).toBe('circle');
    expect(draft.radiusM).toBe(750);
    expect(draft.geometry).toEqual(geofence.definition.geometry);
    expect(draft.effectiveFrom).toBe('2026-09-01T00:00:00Z');
  });
});

describe('definitionFromDrawn', () => {
  it('turns a drawn ring into a centre and a radius', () => {
    const definition = definitionFromDrawn(
      'circle',
      { geometry: drawnCircle(1200) },
      webMercatorCentre,
      meanRadiusM,
    );
    expect(definition).not.toBeNull();
    expect(definition?.geometry.type).toBe('Point');
    const centre = definition?.geometry.type === 'Point' ? definition.geometry.coordinates : null;
    expect(centre).not.toBeNull();
    if (centre !== null) {
      expect(distanceM(centre, CENTRE)).toBeLessThan(0.05);
    }
    // 1200 Web Mercator metres at 8°N is about 1188 m on the ground.
    expect(definition?.radiusM).toBeGreaterThan(1150);
    expect(definition?.radiusM).toBeLessThan(1200);
  });

  it('keeps a polygon and a centre line as drawn', () => {
    expect(definitionFromDrawn('polygon', { geometry: SQUARE }, webMercatorCentre, meanRadiusM)).toEqual({
      geometry: SQUARE,
      radiusM: null,
    });
    const line: Geometry = { type: 'LineString', coordinates: [[80.7, 8.01], [80.8, 8.01]] };
    expect(definitionFromDrawn('corridor', { geometry: line }, webMercatorCentre, meanRadiusM)).toEqual({
      geometry: line,
      radiusM: null,
    });
  });

  it('refuses a shape that is not what the kind needs', () => {
    const point: Geometry = { type: 'Point', coordinates: CENTRE };
    expect(definitionFromDrawn('polygon', { geometry: point }, webMercatorCentre, meanRadiusM)).toBeNull();
    expect(definitionFromDrawn('corridor', { geometry: SQUARE }, webMercatorCentre, meanRadiusM)).toBeNull();
    expect(definitionFromDrawn('circle', { geometry: point }, webMercatorCentre, meanRadiusM)).toBeNull();
  });
});

describe('validateDraft', () => {
  it('accepts a named polygon inside the service area', () => {
    const draft = named({ ...emptyDraft('polygon'), geometry: SQUARE });
    expect(validateDraft(draft, SERVICE_AREA)).toEqual([]);
    expect(draftIsValid(draft, SERVICE_AREA)).toBe(true);
  });

  it('asks for a name and a shape', () => {
    const issues = validateDraft(emptyDraft('polygon'), SERVICE_AREA);
    expect(issues.map((issue) => issue.field)).toEqual(['name', 'geometry']);
  });

  it('refuses a shape that crosses itself', () => {
    const bowTie: Geometry = {
      type: 'Polygon',
      coordinates: [
        [
          [80.74, 8.02],
          [80.78, 8.05],
          [80.78, 8.02],
          [80.74, 8.05],
          [80.74, 8.02],
        ],
      ],
    };
    const issues = validateDraft(named({ ...emptyDraft('polygon'), geometry: bowTie }), SERVICE_AREA);
    expect(issues.some((issue) => issue.message.includes('crosses itself'))).toBe(true);
  });

  it('refuses a geofence that reaches outside the service area', () => {
    const faraway: Geometry = { type: 'Point', coordinates: [100.5, 13.75] };
    const issues = validateDraft(
      named({ ...emptyDraft('circle'), geometry: faraway, radiusM: 500 }),
      SERVICE_AREA,
    );
    expect(issues.some((issue) => issue.message.includes('outside the service area'))).toBe(true);
  });

  it('bounds a circle radius and a corridor half-width as the service does', () => {
    const circle = named({
      ...emptyDraft('circle'),
      geometry: { type: 'Point', coordinates: CENTRE },
      radiusM: MAX_CIRCLE_RADIUS_M + 1,
    });
    expect(validateDraft(circle, SERVICE_AREA).some((issue) => issue.field === 'radiusM')).toBe(true);
    expect(
      validateDraft({ ...circle, radiusM: MAX_CIRCLE_RADIUS_M }, SERVICE_AREA),
    ).toEqual([]);

    const corridor = named({
      ...emptyDraft('corridor'),
      geometry: { type: 'LineString', coordinates: [[80.7, 8.01], [80.8, 8.01]] },
      radiusM: MAX_CORRIDOR_HALF_WIDTH_M + 1,
    });
    expect(validateDraft(corridor, SERVICE_AREA).some((issue) => issue.field === 'radiusM')).toBe(true);
  });

  it('refuses a radius on a polygon and none on a circle', () => {
    expect(
      validateDraft(named({ ...emptyDraft('polygon'), geometry: SQUARE, radiusM: 100 }), SERVICE_AREA),
    ).toEqual([{ field: 'radiusM', message: 'A polygon geofence has no radius.' }]);
    expect(
      validateDraft(
        named({ ...emptyDraft('circle'), geometry: { type: 'Point', coordinates: CENTRE }, radiusM: null }),
        SERVICE_AREA,
      ).some((issue) => issue.field === 'radiusM'),
    ).toBe(true);
  });

  it('checks the sharing policy against the tenants named', () => {
    const draft = named({
      ...emptyDraft('polygon'),
      geometry: SQUARE,
      sharedWithTenants: ['forest-dept'],
    });
    expect(validateDraft(draft, SERVICE_AREA)[0]?.field).toBe('sharedWithTenants');
    expect(validateDraft({ ...draft, sharingPolicy: 'shared' }, SERVICE_AREA)).toEqual([]);
  });

  it('refuses a tenant id that is not one, and a tenant named twice', () => {
    const base = named({
      ...emptyDraft('polygon'),
      geometry: SQUARE,
      sharingPolicy: 'shared' as const,
    });
    expect(
      validateDraft({ ...base, sharedWithTenants: ['Forest Dept'] }, SERVICE_AREA)[0]?.message,
    ).toContain('is not a tenant id');
    expect(
      validateDraft({ ...base, sharedWithTenants: ['forest-dept', 'forest-dept'] }, SERVICE_AREA)[0]
        ?.message,
    ).toContain('named twice');
  });

  it('refuses a period that ends before it starts', () => {
    const draft = named({
      ...emptyDraft('polygon'),
      geometry: SQUARE,
      effectiveFrom: '2026-09-10T00:00:00Z',
      effectiveTo: '2026-09-01T00:00:00Z',
    });
    expect(validateDraft(draft, SERVICE_AREA)[0]?.field).toBe('effectiveDuring');
  });

  it('does not check the service area when it is not known yet', () => {
    const faraway = named({
      ...emptyDraft('circle'),
      geometry: { type: 'Point', coordinates: [100.5, 13.75] },
      radiusM: 500,
    });
    expect(validateDraft(faraway, null)).toEqual([]);
  });
});

describe('draftToInput', () => {
  it('sends the definition, the period and the sharing', () => {
    const input = draftToInput(
      named({
        ...emptyDraft('circle'),
        geometry: { type: 'Point', coordinates: CENTRE },
        radiusM: 750,
        externalId: ' WZ-007 ',
      }),
    );
    expect(input).toEqual({
      name: 'Watch zone',
      description: null,
      externalId: 'WZ-007',
      definition: { kind: 'circle', geometry: { type: 'Point', coordinates: CENTRE }, radiusM: 750 },
      status: 'active',
      effectiveDuring: { from: null, to: null },
      sharingPolicy: 'private',
      sharedWithTenants: [],
      attributes: {},
    });
  });

  it('leaves the radius out of a polygon definition and carries the version of a replace', () => {
    const input = draftToInput({ ...draftFromGeofence(polygonGeofence) });
    expect(input.definition.radiusM).toBeUndefined();
    expect(input.version).toBe(3);
  });

  it('carries the attributes of the geofence it loaded, because a replace replaces everything', () => {
    const withAttributes = {
      ...polygonGeofence,
      attributes: { team: 'north', reviewedBy: 'ranger-4' },
    };
    expect(draftFromGeofence(withAttributes).attributes).toEqual(withAttributes.attributes);
    expect(draftToInput(draftFromGeofence(withAttributes)).attributes).toEqual(
      withAttributes.attributes,
    );
  });

  it('refuses to build a request from a draft with no shape', () => {
    expect(() => draftToInput(named(emptyDraft('polygon')))).toThrow(/without a geometry/);
  });
});

describe('what the editor shows about a draft', () => {
  it('measures a circle exactly and a corridor as its swept area', () => {
    const circle = { ...emptyDraft('circle'), geometry: { type: 'Point' as const, coordinates: CENTRE }, radiusM: 1000 };
    expect(draftAreaM2(circle)).toBeCloseTo(Math.PI * 1_000_000, 3);

    const corridor = {
      ...emptyDraft('corridor'),
      geometry: { type: 'LineString' as const, coordinates: [[80.7, 8.01] as Position, [80.8, 8.01] as Position] },
      radiusM: 50,
    };
    const length = distanceM([80.7, 8.01], [80.8, 8.01]);
    expect(draftAreaM2(corridor)).toBeCloseTo(length * 100 + Math.PI * 2500, 0);
  });

  it('has no area without a shape', () => {
    expect(draftAreaM2(emptyDraft('polygon'))).toBeNull();
    expect(draftShape(emptyDraft('polygon'))).toBeNull();
  });

  it('describes what was drawn', () => {
    expect(describeDraft(emptyDraft('polygon'))).toBe('Nothing drawn yet');
    expect(describeDraft(draftFromGeofence(geofence))).toContain('Circle of 750 m');
    expect(describeDraft(draftFromGeofence(polygonGeofence))).toContain('Area of');
  });

  it('formats metres and areas the way an operator reads them', () => {
    expect(formatMetres(4.25)).toBe('4.3 m');
    expect(formatMetres(512.3)).toBe('512 m');
    expect(formatMetres(2500)).toBe('2.50 km');
    expect(formatArea(1500)).toBe('1,500 m²');
    expect(formatArea(2_500_000)).toBe('2.50 km²');
  });
});
