/**
 * Contract for GET /api/health (shared by server and client; types only).
 *
 * HTTP status: 200 when status is "ok" or "degraded", 503 when "down".
 * The endpoint never returns secrets, tokens or raw error stacks.
 */
export type HealthStatus = 'ok' | 'degraded' | 'down';

export interface HealthResponse {
  status: HealthStatus;
  /** App version from package.json. */
  version: string;
  /** ISO-8601 timestamp of the check. */
  timestamp: string;
  /** Live Unity Catalog probe run on the SQL warehouse with the app service principal. */
  unityCatalog: {
    reachable: boolean;
    /** Identity reported by current_user() (the app service principal id). */
    identity: string | null;
    /** Result of current_catalog(). */
    currentCatalog: string | null;
    /** Configured target catalog / schema and whether the schema exists. */
    catalog: string;
    schema: string;
    schemaExists: boolean | null;
    /** Probe round-trip in milliseconds. */
    latencyMs: number | null;
    /** Short, sanitized failure reason when reachable is false. */
    error: string | null;
  };
}
