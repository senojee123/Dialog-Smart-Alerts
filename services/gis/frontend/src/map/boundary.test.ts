/**
 * The service boundary, asserted against the client's own source.
 *
 * The GIS platform answers geographic questions; deciding who is told what belongs to the services that
 * consume its answers (ADR-0012). The API has a test that its OpenAPI document carries no recipient or
 * notification surface; this is the same test for the map client, so a well-meaning addition - a "notify
 * everyone in this geofence" button - fails the build rather than blurring the boundary.
 */
/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/** `src/`: everything the client is made of. */
const SOURCE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** Words that would mean the client had taken on work that is not the GIS service's. */
const FORBIDDEN: readonly { readonly pattern: RegExp; readonly why: string }[] = [
  { pattern: /\bnotifications?\b/i, why: 'notifications belong to the service that sends them' },
  { pattern: /\bnotify(ing|ies)?\b/i, why: 'the GIS client tells no one anything' },
  { pattern: /\brecipients?\b/i, why: 'the GIS service has no notion of recipients' },
  { pattern: /\bsubscribers?\b/i, why: 'subscriptions are not geography' },
  { pattern: /alert\s*(centre|center)/i, why: 'this client is not an alert centre' },
  { pattern: /\bsms\b/i, why: 'channels are not the GIS client’s business' },
  { pattern: /\bpush\s+message\b/i, why: 'channels are not the GIS client’s business' },
];

function sourceFiles(directory: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...sourceFiles(path));
    } else if (/\.(ts|tsx|css)$/.test(entry.name) && !entry.name.endsWith('boundary.test.ts')) {
      files.push(path);
    }
  }
  return files;
}

describe('the client stays inside the GIS service boundary', () => {
  const files = sourceFiles(SOURCE_ROOT);

  it('reads its own source', () => {
    expect(files.length).toBeGreaterThan(30);
  });

  it('never speaks of notifications, recipients or channels', () => {
    const offences: string[] = [];
    for (const file of files) {
      const content = readFileSync(file, 'utf8');
      for (const line of content.split('\n')) {
        for (const { pattern, why } of FORBIDDEN) {
          if (pattern.test(line)) {
            offences.push(`${file.replace(`${SOURCE_ROOT}/`, '')}: ${line.trim()} (${why})`);
          }
        }
      }
    }
    expect(offences).toEqual([]);
  });

  it('asks the API only for geography', () => {
    const client = readFileSync(join(SOURCE_ROOT, 'services/gisApi.ts'), 'utf8');
    // Every path the client calls is one of the service's geographic endpoints.
    const paths = [...client.matchAll(/'(\/(?:geo\/v1|health)\/[^'`]*)'/g)].map((match) => match[1]);
    expect(paths.length).toBeGreaterThan(8);
    for (const path of paths) {
      expect(path).toMatch(/^\/(geo\/v1|health)\//);
      expect(path).not.toMatch(/notif|alert|recipient|message/i);
    }
  });
});
