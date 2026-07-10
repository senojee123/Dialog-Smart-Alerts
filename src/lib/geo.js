// Geo helpers shared across the UI (single source — mirrors backend spatial.py).

/** Great-circle distance in metres between two lat/lng points. */
export function haversineM(lat1, lng1, lat2, lng2) {
  const R = 6371000, toRad = d => (d * Math.PI) / 180
  const dPhi = toRad(lat2 - lat1), dLmb = toRad(lng2 - lng1)
  const a = Math.sin(dPhi / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLmb / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}
