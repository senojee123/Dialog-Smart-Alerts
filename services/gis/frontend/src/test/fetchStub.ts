/**
 * A `fetch` stand-in for the API tests: it records what was asked and answers what the test queued.
 */
import { vi } from 'vitest';

export interface RecordedRequest {
  readonly url: string;
  readonly method: string;
  readonly headers: Headers;
  readonly body: unknown;
}

export interface QueuedAnswer {
  readonly status?: number;
  readonly body?: unknown;
  readonly headers?: Record<string, string>;
}

export interface FetchStub {
  readonly fetch: typeof fetch;
  readonly requests: RecordedRequest[];
  answer: (answer: QueuedAnswer) => void;
  readonly last: () => RecordedRequest;
}

export function fetchStub(...answers: QueuedAnswer[]): FetchStub {
  const queued = [...answers];
  const requests: RecordedRequest[] = [];

  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const body = init?.body;
    requests.push({
      url: String(input),
      method: init?.method ?? 'GET',
      headers: new Headers(init?.headers),
      body: typeof body === 'string' ? (JSON.parse(body) as unknown) : null,
    });
    const next = queued.shift() ?? { status: 200, body: null };
    const status = next.status ?? 200;
    return new Response(next.body === undefined ? null : JSON.stringify(next.body), {
      status,
      headers: { 'content-type': 'application/json', ...next.headers },
    });
  });

  return {
    fetch: impl as unknown as typeof fetch,
    requests,
    answer: (answer) => {
      queued.push(answer);
    },
    last: () => {
      const request = requests[requests.length - 1];
      if (request === undefined) {
        throw new Error('no request was made');
      }
      return request;
    },
  };
}

/** The query parameters of a recorded request. */
export function parametersOf(request: RecordedRequest): Record<string, string> {
  return Object.fromEntries(new URL(request.url, 'http://test.invalid').searchParams);
}

/** The path of a recorded request, without the query string. */
export function pathOf(request: RecordedRequest): string {
  return new URL(request.url, 'http://test.invalid').pathname;
}
