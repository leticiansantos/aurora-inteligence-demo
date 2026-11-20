/** Stringifies a driver value (text, number, date, uuid) without risking "[object Object]". */
export function text(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'bigint' || typeof v === 'boolean') return String(v);
  if (v instanceof Date) return v.toISOString();
  throw new TypeError('unexpected database value');
}

const TRANSIENT_MESSAGE =
  /timeout exceeded when trying to connect|connection terminated|connection timeout|ECONNRESET|ECONNREFUSED|server closed the connection/i;
const TRANSIENT_CODE = /^(08|53|57P0|ECONN|ETIMEDOUT|ENOTFOUND|EAI_)/;

/**
 * Cold-start / dropped-connection failures. The pg driver often raises them WITHOUT a SQLSTATE code
 * ("timeout exceeded when trying to connect", "Connection terminated unexpectedly") while the Lakebase
 * endpoint wakes from scale-to-zero.
 */
export function isTransientConnectionError(err: unknown): boolean {
  const code = (err as { code?: unknown } | null)?.code;
  if (typeof code === 'string' && TRANSIENT_CODE.test(code)) return true;
  const message = err instanceof Error ? err.message : '';
  return TRANSIENT_MESSAGE.test(message);
}

export interface QueryLike {
  query(text: string, params?: unknown[]): Promise<{ rows: Record<string, unknown>[] }>;
}

/**
 * Retries a query ONCE on a transient connection error (endpoint waking up). A retried INSERT can at worst
 * hit the partial unique index (409), never create a duplicate row.
 */
export function withConnectionRetry<T extends QueryLike>(
  db: T,
  delayMs = 750,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms))
): QueryLike {
  return {
    async query(text, params) {
      try {
        return await db.query(text, params);
      } catch (err) {
        if (!isTransientConnectionError(err)) throw err;
        await sleep(delayMs);
        return db.query(text, params);
      }
    },
  };
}
