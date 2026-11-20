import type { HealthResponse } from '../../../shared/health';

export type { HealthResponse, HealthStatus } from '../../../shared/health';

/** Typed client for GET /api/health (contract: app/shared/health.ts). */
export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const res = await fetch('/api/health', { signal, headers: { Accept: 'application/json' } });
  // 503 carries a valid body with status "down"; only fail on non-JSON.
  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    throw new Error(`Resposta inesperada do servidor (HTTP ${res.status})`);
  }
  return (await res.json()) as HealthResponse;
}
