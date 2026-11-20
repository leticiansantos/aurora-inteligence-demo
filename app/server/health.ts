import type { sql } from '@databricks/appkit';
import type { HealthResponse, HealthStatus } from '../shared/health.js';

/** Minimal slice of the AppKit analytics plugin that the health check needs. */
export interface HealthQueryRunner {
  query(
    statement: string,
    parameters: Record<string, ParameterMarker>,
    formatParameters?: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<unknown>;
}

// Parameter markers are created by `sql.string()` in AppKit.
export type ParameterMarker = ReturnType<typeof sql.string>;

export interface HealthConfig {
  version: string;
  catalog: string;
  schema: string;
  /** Builds a string parameter marker (injected so tests need no AppKit). */
  stringParam: (value: string) => ParameterMarker;
  /** Upper bound for the warehouse round trip, ms (covers a cold start). */
  timeoutMs?: number;
  now?: () => Date;
}

/**
 * Probe SQL. Catalog and schema are bound parameters (never interpolated):
 * IDENTIFIER() resolves the catalog's information_schema at runtime, so the
 * check only needs USE CATALOG for the app service principal.
 */
export const HEALTH_SQL = `SELECT current_catalog() AS current_catalog,
       current_user() AS identity,
       EXISTS(
         SELECT 1
         FROM IDENTIFIER(:target_catalog || '.information_schema.schemata')
         WHERE schema_name = :target_schema
       ) AS schema_exists`;

const DEFAULT_TIMEOUT_MS = 45_000;

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function asBoolean(value: unknown): boolean | null {
  if (typeof value === 'boolean') return value;
  // The SQL warehouse JSON API returns booleans as strings.
  if (value === 'true') return true;
  if (value === 'false') return false;
  return null;
}

function firstRow(result: unknown): Record<string, unknown> | null {
  if (typeof result !== 'object' || result === null) return null;
  const data = (result as { data?: unknown }).data;
  if (!Array.isArray(data) || data.length === 0) return null;
  const row: unknown = data[0];
  return typeof row === 'object' && row !== null ? (row as Record<string, unknown>) : null;
}

/** Short, sanitized failure reason: never includes tokens, hosts or stacks. */
export function sanitizeError(err: unknown): string {
  if (err instanceof Error && err.name === 'AbortError') return 'warehouse query timed out';
  const message = err instanceof Error ? err.message : String(err);
  if (/PERMISSION_DENIED|USE CATALOG|USE SCHEMA|not authorized|insufficient privileges/i.test(message)) {
    return 'permission denied for the app service principal';
  }
  if (/timed? ?out|timeout/i.test(message)) return 'warehouse query timed out';
  return 'warehouse query failed';
}

export async function runHealthCheck(
  runner: HealthQueryRunner,
  config: HealthConfig,
): Promise<{ httpStatus: 200 | 503; body: HealthResponse }> {
  const now = config.now ?? (() => new Date());
  const unityCatalog: HealthResponse['unityCatalog'] = {
    reachable: false,
    identity: null,
    currentCatalog: null,
    catalog: config.catalog,
    schema: config.schema,
    schemaExists: null,
    latencyMs: null,
    error: null,
  };

  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  try {
    const result = await runner.query(
      HEALTH_SQL,
      {
        target_catalog: config.stringParam(config.catalog),
        target_schema: config.stringParam(config.schema),
      },
      undefined,
      controller.signal,
    );
    const row = firstRow(result);
    if (!row) throw new Error('empty result');
    unityCatalog.reachable = true;
    unityCatalog.latencyMs = Date.now() - started;
    unityCatalog.identity = asString(row.identity);
    unityCatalog.currentCatalog = asString(row.current_catalog);
    unityCatalog.schemaExists = asBoolean(row.schema_exists);
  } catch (err) {
    unityCatalog.latencyMs = Date.now() - started;
    unityCatalog.error = sanitizeError(err);
  } finally {
    clearTimeout(timer);
  }

  let status: HealthStatus;
  if (!unityCatalog.reachable) status = 'down';
  else if (unityCatalog.schemaExists === true) status = 'ok';
  else status = 'degraded';

  return {
    httpStatus: status === 'down' ? 503 : 200,
    body: { status, version: config.version, timestamp: now().toISOString(), unityCatalog },
  };
}
