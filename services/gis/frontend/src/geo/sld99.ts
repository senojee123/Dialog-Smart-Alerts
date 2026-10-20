/**
 * SLD99 / Sri Lanka Grid 1999 (EPSG:5235): the plane the platform measures metres on.
 *
 * The API answers every distance in metres on this plane (ADR-02), so the client measures the same way:
 * a radius drawn on the map, the length of a ruler and the `distanceM` of a query answer are then the
 * same quantity. The transformation is the pipeline PROJ uses for EPSG:4326 -> EPSG:5235:
 *
 * 1. WGS84 geodetic -> WGS84 geocentric (ECEF)
 * 2. the inverse of the published "SLD99 to WGS 84 (1)" Helmert transformation (coordinate frame
 *    convention) -> SLD99 geocentric
 * 3. SLD99 geocentric -> SLD99 geodetic, on the Everest 1830 (1937 Adjustment) ellipsoid
 * 4. Transverse Mercator (EPSG method 9807) with the Sri Lanka Grid 1999 parameters
 *
 * `sld99.test.ts` checks the implementation against values exported from PROJ itself
 * (`sld99Reference.generated.ts`), forwards and back.
 *
 * The datum change carries the published 14 m accuracy of that Helmert transformation. It is a
 * near-constant offset over a local area, so distances between points transformed the same way keep
 * their accuracy; see ARCHITECTURE.md, "Coordinate systems".
 */

/** `[longitude, latitude]` in WGS84 degrees, as GeoJSON orders them (RFC 7946). */
export type Position = readonly [number, number];

/** `[easting, northing]` in metres on the EPSG:5235 plane. */
export type MetricPoint = readonly [number, number];

const WGS84 = { a: 6378137.0, inverseFlattening: 298.257223563 } as const;
const EVEREST_1830 = { a: 6377276.345, inverseFlattening: 300.8017 } as const;

/** "SLD99 to WGS 84 (1)" (EPSG:15926): metres, arc seconds and parts per million. */
const HELMERT = {
  tx: -0.293,
  ty: 766.95,
  tz: 87.713,
  rxSec: -0.195704,
  rySec: -1.695068,
  rzSec: -3.473016,
  scalePpm: -0.039338,
} as const;

/** Sri Lanka Grid 1999 (EPSG:19945). */
const GRID = {
  latitudeOfOrigin: 7.00047152777778,
  longitudeOfOrigin: 80.7717130833333,
  scaleFactor: 0.9999238418,
  falseEasting: 500000.0,
  falseNorthing: 500000.0,
} as const;

const DEGREES = Math.PI / 180;
const ARC_SECONDS = Math.PI / (180 * 3600);

interface Ellipsoid {
  readonly a: number;
  readonly inverseFlattening: number;
}

function eccentricitySquared({ inverseFlattening }: Ellipsoid): number {
  const f = 1 / inverseFlattening;
  return f * (2 - f);
}

function geodeticToEcef(
  [lon, lat]: Position,
  ellipsoid: Ellipsoid,
): readonly [number, number, number] {
  const e2 = eccentricitySquared(ellipsoid);
  const phi = lat * DEGREES;
  const lambda = lon * DEGREES;
  const sinPhi = Math.sin(phi);
  const cosPhi = Math.cos(phi);
  // Radius of curvature in the prime vertical; heights are zero, the API is two-dimensional.
  const nu = ellipsoid.a / Math.sqrt(1 - e2 * sinPhi * sinPhi);
  return [nu * cosPhi * Math.cos(lambda), nu * cosPhi * Math.sin(lambda), nu * (1 - e2) * sinPhi];
}

function ecefToGeodetic(
  [x, y, z]: readonly [number, number, number],
  ellipsoid: Ellipsoid,
): Position {
  const e2 = eccentricitySquared(ellipsoid);
  const p = Math.hypot(x, y);
  // Bowring's starting value, then fixed-point iteration; it converges to float precision in a few
  // rounds at these latitudes, and the loop is bounded so a degenerate input cannot spin.
  let phi = Math.atan2(z, p * (1 - e2));
  for (let round = 0; round < 8; round += 1) {
    const sinPhi = Math.sin(phi);
    const nu = ellipsoid.a / Math.sqrt(1 - e2 * sinPhi * sinPhi);
    const next = Math.atan2(z + e2 * nu * sinPhi, p);
    if (Math.abs(next - phi) < 1e-15) {
      phi = next;
      break;
    }
    phi = next;
  }
  return [Math.atan2(y, x) / DEGREES, phi / DEGREES];
}

/** WGS84 geocentric -> SLD99 geocentric: the inverse of the published transformation. */
function helmertToSld99([x, y, z]: readonly [number, number, number]): readonly [number, number, number] {
  const rx = HELMERT.rxSec * ARC_SECONDS;
  const ry = HELMERT.rySec * ARC_SECONDS;
  const rz = HELMERT.rzSec * ARC_SECONDS;
  const scale = 1 + HELMERT.scalePpm * 1e-6;
  const dx = x - HELMERT.tx;
  const dy = y - HELMERT.ty;
  const dz = z - HELMERT.tz;
  // Coordinate frame convention: the forward rotation is [[1, rz, -ry], [-rz, 1, rx], [ry, -rx, 1]];
  // its inverse is the transpose (the angles are of the order of a microradian).
  return [
    (dx - rz * dy + ry * dz) / scale,
    (rz * dx + dy - rx * dz) / scale,
    (-ry * dx + rx * dy + dz) / scale,
  ];
}

/** SLD99 geocentric -> WGS84 geocentric: the published transformation itself. */
function helmertToWgs84([x, y, z]: readonly [number, number, number]): readonly [number, number, number] {
  const rx = HELMERT.rxSec * ARC_SECONDS;
  const ry = HELMERT.rySec * ARC_SECONDS;
  const rz = HELMERT.rzSec * ARC_SECONDS;
  const scale = 1 + HELMERT.scalePpm * 1e-6;
  return [
    HELMERT.tx + scale * (x + rz * y - ry * z),
    HELMERT.ty + scale * (-rz * x + y + rx * z),
    HELMERT.tz + scale * (ry * x - rx * y + z),
  ];
}

/** Rectifying-latitude series of the meridian arc, in terms of the third flattening. */
function meridianArc(phi: number, n: number, b: number): number {
  return (
    b *
    (phi -
      (3 / 2) * (n - (9 / 16) * n ** 3) * Math.sin(2 * phi) +
      (15 / 16) * (n ** 2 - (3 / 4) * n ** 4) * Math.sin(4 * phi) -
      (35 / 48) * n ** 3 * Math.sin(6 * phi) +
      (315 / 512) * n ** 4 * Math.sin(8 * phi))
  );
}

function thirdFlattening({ inverseFlattening }: Ellipsoid): number {
  const f = 1 / inverseFlattening;
  return f / (2 - f);
}

function rectifyingRadius(ellipsoid: Ellipsoid, n: number): number {
  return (ellipsoid.a / (1 + n)) * (1 + n ** 2 / 4 + n ** 4 / 64);
}

/** SLD99 geodetic -> Sri Lanka Grid 1999 easting and northing (EPSG method 9807). */
function transverseMercator([lon, lat]: Position): MetricPoint {
  const e2 = eccentricitySquared(EVEREST_1830);
  const n = thirdFlattening(EVEREST_1830);
  const b = rectifyingRadius(EVEREST_1830, n);
  const phi = lat * DEGREES;
  const dLambda = (lon - GRID.longitudeOfOrigin) * DEGREES;

  const sinPhi = Math.sin(phi);
  const cosPhi = Math.cos(phi);
  const t = Math.tan(phi);
  const nu = EVEREST_1830.a / Math.sqrt(1 - e2 * sinPhi * sinPhi);
  const rho = (EVEREST_1830.a * (1 - e2)) / (1 - e2 * sinPhi * sinPhi) ** 1.5;
  const eta2 = nu / rho - 1;

  const easting =
    GRID.falseEasting +
    GRID.scaleFactor *
      nu *
      (dLambda * cosPhi +
        ((dLambda * cosPhi) ** 3 / 6) * (1 - t * t + eta2) +
        ((dLambda * cosPhi) ** 5 / 120) *
          (5 - 18 * t ** 2 + t ** 4 + 14 * eta2 - 58 * t ** 2 * eta2) +
        ((dLambda * cosPhi) ** 7 / 5040) * (61 - 479 * t ** 2 + 179 * t ** 4 - t ** 6));

  const northing =
    GRID.falseNorthing +
    GRID.scaleFactor *
      (meridianArc(phi, n, b) -
        meridianArc(GRID.latitudeOfOrigin * DEGREES, n, b) +
        nu *
          t *
          ((dLambda * cosPhi) ** 2 / 2 +
            ((dLambda * cosPhi) ** 4 / 24) * (5 - t ** 2 + 9 * eta2 + 4 * eta2 ** 2) +
            ((dLambda * cosPhi) ** 6 / 720) *
              (61 - 58 * t ** 2 + t ** 4 + 270 * eta2 - 330 * t ** 2 * eta2) +
            ((dLambda * cosPhi) ** 8 / 40320) * (1385 - 3111 * t ** 2 + 543 * t ** 4 - t ** 6)));

  return [easting, northing];
}

/** Sri Lanka Grid 1999 easting and northing -> SLD99 geodetic. */
function inverseTransverseMercator([easting, northing]: MetricPoint): Position {
  const e2 = eccentricitySquared(EVEREST_1830);
  const n = thirdFlattening(EVEREST_1830);
  const b = rectifyingRadius(EVEREST_1830, n);

  const arc =
    meridianArc(GRID.latitudeOfOrigin * DEGREES, n, b) +
    (northing - GRID.falseNorthing) / GRID.scaleFactor;
  // Footpoint latitude: the latitude whose meridian arc is `arc`. Newton on the arc converges in three
  // rounds because d(arc)/d(phi) is close to b.
  let phi1 = arc / b;
  for (let round = 0; round < 8; round += 1) {
    const delta = (arc - meridianArc(phi1, n, b)) / b;
    phi1 += delta;
    if (Math.abs(delta) < 1e-15) {
      break;
    }
  }

  const sinPhi = Math.sin(phi1);
  const cosPhi = Math.cos(phi1);
  const t = Math.tan(phi1);
  const nu = EVEREST_1830.a / Math.sqrt(1 - e2 * sinPhi * sinPhi);
  const rho = (EVEREST_1830.a * (1 - e2)) / (1 - e2 * sinPhi * sinPhi) ** 1.5;
  const eta2 = nu / rho - 1;
  const x = (easting - GRID.falseEasting) / (GRID.scaleFactor * nu);

  const lat =
    phi1 -
    ((nu * t) / rho) *
      ((x ** 2 / 2) * 1 -
        (x ** 4 / 24) * (5 + 3 * t ** 2 + eta2 - 9 * eta2 * t ** 2 - 4 * eta2 ** 2) +
        (x ** 6 / 720) * (61 + 90 * t ** 2 + 45 * t ** 4 + 46 * eta2 - 252 * t ** 2 * eta2) -
        (x ** 8 / 40320) * (1385 + 3633 * t ** 2 + 4095 * t ** 4 + 1575 * t ** 6));

  const lon =
    GRID.longitudeOfOrigin * DEGREES +
    (x -
      (x ** 3 / 6) * (1 + 2 * t ** 2 + eta2) +
      (x ** 5 / 120) * (5 + 28 * t ** 2 + 24 * t ** 4 + 6 * eta2 + 8 * eta2 * t ** 2) -
      (x ** 7 / 5040) * (61 + 662 * t ** 2 + 1320 * t ** 4 + 720 * t ** 6)) /
      cosPhi;

  return [lon / DEGREES, lat / DEGREES];
}

/** WGS84 `[lon, lat]` -> EPSG:5235 `[easting, northing]` in metres. */
export function toMetric(position: Position): MetricPoint {
  return transverseMercator(
    ecefToGeodetic(helmertToSld99(geodeticToEcef(position, WGS84)), EVEREST_1830),
  );
}

/** EPSG:5235 `[easting, northing]` -> WGS84 `[lon, lat]`. */
export function toWgs84(point: MetricPoint): Position {
  return ecefToGeodetic(
    helmertToWgs84(geodeticToEcef(inverseTransverseMercator(point), EVEREST_1830)),
    WGS84,
  );
}

/** Distance in metres on the EPSG:5235 plane: the quantity the API calls `distanceM`. */
export function distanceM(from: Position, to: Position): number {
  const [fromEasting, fromNorthing] = toMetric(from);
  const [toEasting, toNorthing] = toMetric(to);
  return Math.hypot(toEasting - fromEasting, toNorthing - fromNorthing);
}

/** Length of a path through `positions`, in metres. Fewer than two positions measure zero. */
export function pathLengthM(positions: readonly Position[]): number {
  let total = 0;
  for (let index = 1; index < positions.length; index += 1) {
    const previous = positions[index - 1];
    const current = positions[index];
    if (previous !== undefined && current !== undefined) {
      total += distanceM(previous, current);
    }
  }
  return total;
}

/** Metres per degree of latitude and of longitude at `position`, for pixel-scale estimates. */
export function metresPerDegree(position: Position): { readonly lon: number; readonly lat: number } {
  const [lon, lat] = position;
  const delta = 0.01;
  return {
    lon: distanceM([lon - delta, lat], [lon + delta, lat]) / (2 * delta),
    lat: distanceM([lon, lat - delta], [lon, lat + delta]) / (2 * delta),
  };
}
