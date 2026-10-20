/**
 * `datetime-local` inputs work in the browser's own time zone; the API speaks UTC. These two functions
 * are the only place that conversion happens.
 */

export function toLocalInput(iso: string | null): string {
  if (iso === null) {
    return '';
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function fromLocalInput(value: string): string | null {
  if (value === '') {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
