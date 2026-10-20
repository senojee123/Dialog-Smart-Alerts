/**
 * The HTTP boundary: one place that knows about the tenant header, query strings, RFC 9457 problem details
 * and response validation. Everything above it works with typed values or an `ApiError`.
 *
 * The GIS runs as an instance of the main platform, which owns users and sign-in: no credentials are sent.
 * A request acts for the tenant in `X-GIS-Tenant-Id`, else for the platform's organisation (`GIS_TENANT_ID`).
 */
import type { z } from 'zod';

import { config } from '../config';
import { problemSchema, type Problem } from '../types/api';

const DEFAULT_TIMEOUT_MS = 15_000;
const PROBLEM_TYPE_PREFIX = 'urn:gis-core-service:problem:';
const RFC9457_MEMBERS = new Set(['type', 'title', 'status', 'detail', 'instance', 'requestId']);

/** The header naming the tenant (organisation) a request acts for. */
export const TENANT_HEADER = 'X-GIS-Tenant-Id';

export type QueryValue = string | number | boolean | null | undefined;

/** An API call failed: HTTP error (with problem details when provided), network error or bad payload. */
export class ApiError extends Error {
  readonly status: number | null;
  readonly problem: Problem | null;
  readonly requestId: string | null;

  constructor(
    message: string,
    options: {
      status?: number | null;
      problem?: Problem | null;
      requestId?: string | null;
      cause?: unknown;
    },
  ) {
    super(message, { cause: options.cause });
    this.name = 'ApiError';
    this.status = options.status ?? null;
    this.problem = options.problem ?? null;
    this.requestId = options.requestId ?? null;
  }

  /** The service's problem code (`invalid_geometry`, `version_conflict`, ...), when it sent one. */
  get code(): string | null {
    const type = this.problem?.type;
    return type?.startsWith(PROBLEM_TYPE_PREFIX) === true
      ? type.slice(PROBLEM_TYPE_PREFIX.length)
      : null;
  }

  /** Problem members beyond RFC 9457's own, e.g. `supportedFilters` or `currentVersion`. */
  get extensions(): Readonly<Record<string, unknown>> {
    return Object.fromEntries(
      Object.entries(this.problem ?? {}).filter(([name]) => !RFC9457_MEMBERS.has(name)),
    );
  }

  /** What to show an operator: the service's `detail` when it sent one, else the message. */
  get summary(): string {
    return this.problem?.detail ?? this.problem?.title ?? this.message;
  }
}

export interface ClientOptions {
  readonly baseUrl?: string;
  /** Tenant the requests act for; `null` leaves it to the service (the platform's organisation). */
  readonly tenantId?: string | null;
  readonly fetchImpl?: typeof fetch;
  readonly timeoutMs?: number;
}

export interface RequestOptions<T> {
  readonly method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  readonly path: string;
  readonly schema?: z.ZodType<T>;
  readonly query?: Readonly<Record<string, QueryValue>>;
  readonly body?: unknown;
  readonly signal?: AbortSignal;
  /** HTTP statuses whose body is valid data for this call (e.g. 503 for the readiness probe). */
  readonly acceptStatuses?: readonly number[];
}

export interface ApiResponse<T> {
  readonly data: T;
  readonly status: number;
  readonly requestId: string | null;
  readonly headers: Headers;
}

/** Query string from defined values only, so an absent filter is absent rather than empty. */
export function queryString(query: Readonly<Record<string, QueryValue>> = {}): string {
  const parameters = new URLSearchParams();
  for (const [name, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') {
      parameters.set(name, String(value));
    }
  }
  const rendered = parameters.toString();
  return rendered === '' ? '' : `?${rendered}`;
}

async function readJson(response: Response, path: string): Promise<unknown> {
  const text = await response.text();
  if (text === '') {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch (cause) {
    throw new ApiError(`Response from ${path} is not valid JSON`, {
      status: response.status,
      requestId: response.headers.get('x-request-id'),
      cause,
    });
  }
}

/** An API client bound to a base URL and the tenant its requests act for. */
export class ApiClient {
  private readonly baseUrl: string;
  private readonly tenantId: string | null;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(options: ClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? config.apiBaseUrl).replace(/\/+$/, '');
    this.tenantId = options.tenantId === undefined ? config.tenantId : options.tenantId;
    this.fetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  async send<T>(options: RequestOptions<T>): Promise<ApiResponse<T>> {
    const { method = 'GET', path, schema, query, body, signal, acceptStatuses = [200, 201] } = options;
    const url = `${this.baseUrl}${path}${queryString(query)}`;
    const timeout = AbortSignal.timeout(this.timeoutMs);
    const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

    const headers = new Headers({
      Accept: 'application/json, application/geo+json, application/problem+json',
    });
    if (this.tenantId !== null && this.tenantId !== '') {
      headers.set(TENANT_HEADER, this.tenantId);
    }
    if (body !== undefined) {
      headers.set('Content-Type', 'application/json');
    }

    let response: Response;
    try {
      response = await this.fetchImpl(url, {
        method,
        headers,
        signal: combined,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (cause) {
      if (signal?.aborted) {
        throw cause;
      }
      const reason = timeout.aborted ? `timed out after ${this.timeoutMs} ms` : 'network error';
      throw new ApiError(`Request to ${path} failed: ${reason}`, { cause });
    }

    const requestId = response.headers.get('x-request-id');
    const payload = await readJson(response, path);

    if (!acceptStatuses.includes(response.status)) {
      const problem = problemSchema.safeParse(payload);
      const detail = problem.success ? (problem.data.detail ?? problem.data.title) : response.statusText;
      throw new ApiError(`Request to ${path} failed with HTTP ${response.status}: ${detail}`, {
        status: response.status,
        problem: problem.success ? problem.data : null,
        requestId,
      });
    }

    if (schema === undefined) {
      return { data: undefined as T, status: response.status, requestId, headers: response.headers };
    }
    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      const issue = parsed.error.issues[0];
      const where = issue === undefined ? 'invalid' : `${issue.path.join('.')}: ${issue.message}`;
      throw new ApiError(`Unexpected response shape from ${path} (${where})`, {
        status: response.status,
        requestId,
        cause: parsed.error,
      });
    }
    return { data: parsed.data, status: response.status, requestId, headers: response.headers };
  }

  async get<T>(path: string, schema: z.ZodType<T>, options: Omit<RequestOptions<T>, 'path' | 'schema' | 'method' | 'body'> = {}): Promise<T> {
    const response = await this.send({ ...options, method: 'GET', path, schema, acceptStatuses: options.acceptStatuses ?? [200] });
    return response.data;
  }

  async post<T>(path: string, body: unknown, schema: z.ZodType<T>, options: Omit<RequestOptions<T>, 'path' | 'schema' | 'method' | 'body'> = {}): Promise<ApiResponse<T>> {
    return this.send({ ...options, method: 'POST', path, body, schema });
  }

  async put<T>(path: string, body: unknown, schema: z.ZodType<T>, options: Omit<RequestOptions<T>, 'path' | 'schema' | 'method' | 'body'> = {}): Promise<ApiResponse<T>> {
    return this.send({ ...options, method: 'PUT', path, body, schema });
  }

  async delete(path: string, options: Omit<RequestOptions<undefined>, 'path' | 'schema' | 'method' | 'body'> = {}): Promise<void> {
    await this.send<undefined>({ ...options, method: 'DELETE', path, acceptStatuses: options.acceptStatuses ?? [200, 204] });
  }
}
