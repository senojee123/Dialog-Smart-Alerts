import { describe, expect, it } from 'vitest';
import { z } from 'zod';

import { fetchStub, parametersOf } from '../test/fetchStub';
import { ApiClient, ApiError, queryString } from './apiClient';

const schema = z.object({ ok: z.boolean() });

function client(stub: ReturnType<typeof fetchStub>, tenantId: string | null = 'wildlife-dept') {
  return new ApiClient({ baseUrl: '/api', fetchImpl: stub.fetch, tenantId });
}

describe('queryString', () => {
  it('leaves out what was not set', () => {
    expect(queryString({ a: 1, b: null, c: undefined, d: '', e: false })).toBe('?a=1&e=false');
  });

  it('is empty when nothing was set', () => {
    expect(queryString({})).toBe('');
    expect(queryString()).toBe('');
  });
});

describe('ApiClient', () => {
  it('names the tenant, sends no credentials and asks for problem details', async () => {
    const stub = fetchStub({ body: { ok: true } });
    await client(stub).get('/thing', schema);
    expect(stub.last().headers.get('X-GIS-Tenant-Id')).toBe('wildlife-dept');
    expect(stub.last().headers.get('Authorization')).toBeNull();
    expect(stub.last().headers.get('Accept')).toContain('application/problem+json');
  });

  it('leaves the tenant to the service when none is configured', async () => {
    const stub = fetchStub({ body: { ok: true } });
    await client(stub, null).get('/thing', schema);
    expect(stub.last().headers.get('X-GIS-Tenant-Id')).toBeNull();
  });

  it('puts the query parameters it was given on the URL', async () => {
    const stub = fetchStub({ body: { ok: true } });
    await client(stub).get('/thing', schema, { query: { tenantId: 'wildlife-dept', limit: 10 } });
    expect(parametersOf(stub.last())).toEqual({ tenantId: 'wildlife-dept', limit: '10' });
  });

  it('serialises a body and sets the content type', async () => {
    const stub = fetchStub({ status: 201, body: { ok: true } });
    const response = await client(stub).post('/thing', { target: 'ref.settlement' }, schema);
    expect(stub.last().method).toBe('POST');
    expect(stub.last().headers.get('Content-Type')).toBe('application/json');
    expect(stub.last().body).toEqual({ target: 'ref.settlement' });
    expect(response.status).toBe(201);
  });

  it('turns problem details into an ApiError with its code and extensions', async () => {
    const stub = fetchStub({
      status: 422,
      body: {
        type: 'urn:gis-core-service:problem:unsupported_filter',
        title: 'Filter not supported',
        status: 422,
        detail: "Layer 'ref.road' has no filter 'severity'.",
        supportedFilters: ['type', 'refCode'],
      },
      headers: { 'x-request-id': 'req-7' },
    });
    const error = await client(stub)
      .get('/thing', schema)
      .catch((cause: unknown) => cause);
    expect(error).toBeInstanceOf(ApiError);
    const problem = error as ApiError;
    expect(problem.status).toBe(422);
    expect(problem.code).toBe('unsupported_filter');
    expect(problem.summary).toBe("Layer 'ref.road' has no filter 'severity'.");
    expect(problem.requestId).toBe('req-7');
    expect(problem.extensions).toEqual({ supportedFilters: ['type', 'refCode'] });
  });

  it('has no code when the problem type is not one of the service own types', async () => {
    const stub = fetchStub({ status: 500, body: { type: 'about:blank', title: 'Oops', status: 500 } });
    const error = (await client(stub)
      .get('/thing', schema)
      .catch((cause: unknown) => cause)) as ApiError;
    expect(error.code).toBeNull();
    expect(error.summary).toBe('Oops');
  });

  it('rejects a response that does not match the schema, naming the field', async () => {
    const stub = fetchStub({ body: { ok: 'yes' } });
    const error = (await client(stub)
      .get('/thing', schema)
      .catch((cause: unknown) => cause)) as ApiError;
    expect(error.message).toContain('Unexpected response shape');
    expect(error.message).toContain('ok');
  });

  it('accepts the statuses a call says are data', async () => {
    const stub = fetchStub({ status: 503, body: { ok: false } });
    const answer = await client(stub).get('/health/ready', schema, { acceptStatuses: [200, 503] });
    expect(answer.ok).toBe(false);
  });

  it('reports a network failure as an ApiError', async () => {
    const failing = {
      fetch: (() => Promise.reject(new Error('offline'))) as unknown as typeof fetch,
      requests: [],
      answer: () => undefined,
      last: () => {
        throw new Error('none');
      },
    };
    const error = (await new ApiClient({ baseUrl: '/api', fetchImpl: failing.fetch, tenantId: null })
      .get('/thing', schema)
      .catch((cause: unknown) => cause)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toContain('network error');
  });

  it('deletes without expecting a body', async () => {
    const stub = fetchStub({ status: 204 });
    await client(stub).delete('/geo/v1/geofences/abc', { query: { purge: true } });
    expect(stub.last().method).toBe('DELETE');
    expect(parametersOf(stub.last())).toEqual({ purge: 'true' });
  });
});
