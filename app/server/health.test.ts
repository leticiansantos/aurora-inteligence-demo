import { sql } from '@databricks/appkit';
import { describe, expect, it } from 'vitest';
import { runHealthCheck, sanitizeError, type HealthQueryRunner } from './health.js';

const base = {
  version: '1.2.3',
  catalog: 'classic_stable',
  schema: 'auto_intelligence',
  stringParam: (value: string) => sql.string(value),
  now: () => new Date('2026-01-01T00:00:00Z'),
};

const runnerReturning = (data: unknown[]): HealthQueryRunner => ({
  query: () => Promise.resolve({ data }),
});

describe('runHealthCheck', () => {
  it('returns ok when the probe succeeds and the schema exists', async () => {
    const { httpStatus, body } = await runHealthCheck(
      runnerReturning([{ current_catalog: 'classic_stable', identity: 'sp-uuid', schema_exists: 'true' }]),
      base,
    );
    expect(httpStatus).toBe(200);
    expect(body.status).toBe('ok');
    expect(body.version).toBe('1.2.3');
    expect(body.unityCatalog).toMatchObject({
      reachable: true,
      identity: 'sp-uuid',
      currentCatalog: 'classic_stable',
      schemaExists: true,
      error: null,
    });
  });

  it('returns degraded (200) when the schema is missing', async () => {
    const { httpStatus, body } = await runHealthCheck(
      runnerReturning([{ current_catalog: 'classic_stable', identity: 'sp', schema_exists: 'false' }]),
      base,
    );
    expect(httpStatus).toBe(200);
    expect(body.status).toBe('degraded');
    expect(body.unityCatalog.schemaExists).toBe(false);
  });

  it('returns down (503) with a sanitized error when the query fails', async () => {
    const runner: HealthQueryRunner = {
      query: () => Promise.reject(new Error('PERMISSION_DENIED: token dapi123 https://host/secret')),
    };
    const { httpStatus, body } = await runHealthCheck(runner, base);
    expect(httpStatus).toBe(503);
    expect(body.status).toBe('down');
    expect(body.unityCatalog.reachable).toBe(false);
    expect(JSON.stringify(body)).not.toMatch(/dapi|https?:/);
  });

  it('treats an empty result as down', async () => {
    const { body } = await runHealthCheck(runnerReturning([]), base);
    expect(body.status).toBe('down');
  });

  it('passes catalog and schema as bound parameters, not SQL text', async () => {
    let seen: { sql: string; params: Record<string, object> } | undefined;
    const runner: HealthQueryRunner = {
      query: (statement, params) => {
        seen = { sql: statement, params };
        return Promise.resolve({ data: [{ identity: 'sp', current_catalog: 'c', schema_exists: 'true' }] });
      },
    };
    await runHealthCheck(runner, base);
    expect(seen?.sql).not.toContain('classic_stable');
    expect(seen?.params).toEqual({
      target_catalog: sql.string('classic_stable'),
      target_schema: sql.string('auto_intelligence'),
    });
  });

  it('aborts and reports down on timeout', async () => {
    const runner: HealthQueryRunner = {
      query: (_s, _p, _f, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            const e = new Error('aborted');
            e.name = 'AbortError';
            reject(e);
          });
        }),
    };
    const { body } = await runHealthCheck(runner, { ...base, timeoutMs: 10 });
    expect(body.status).toBe('down');
    expect(body.unityCatalog.error).toBe('warehouse query timed out');
  });
});

describe('sanitizeError', () => {
  it('maps permission errors', () => {
    expect(sanitizeError(new Error('User does not have USE CATALOG'))).toMatch(/permission denied/);
  });
});
