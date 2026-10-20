/**
 * Handing an export to the browser as a file.
 *
 * The export is read through the API client like any other answer - with the tenant header, validated -
 * and then saved from memory, so nothing has to travel in a URL.
 */

export type SaveFile = (content: unknown, filename: string) => void;

export const saveGeoJson: SaveFile = (content, filename) => {
  const blob = new Blob([JSON.stringify(content)], { type: 'application/geo+json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked on the next tick: some browsers start the download only after the click handler returns.
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
};

/** `ops.geofence` exported at `2026-09-23T10:15:00Z` -> `ops-geofence-20260923T101500Z.geojson`. */
export function exportFilename(what: string, exportedAt: string): string {
  const time = new Date(exportedAt);
  const stamp = Number.isNaN(time.getTime())
    ? ''
    : `-${time.toISOString().slice(0, 19).replace(/[-:]/g, '')}Z`;
  return `${what.toLowerCase().replace(/[^a-z0-9]+/g, '-')}${stamp}.geojson`;
}
