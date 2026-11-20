/** Tiny in-memory TTL cache that also de-duplicates concurrent loads. Failures are never cached. */
export class TtlCache {
  private readonly entries = new Map<string, { expires: number; value: Promise<unknown>; at: number }>();

  constructor(
    private readonly ttlMs: number,
    private readonly now: () => number = Date.now,
    private readonly maxEntries = 500
  ) {}

  /** Returns [value, cached]; `cached` is true when the value was not loaded by this call. */
  async get<T>(key: string, load: () => Promise<T>): Promise<{ value: T; cached: boolean; at: number }> {
    const hit = this.entries.get(key);
    if (hit && hit.expires > this.now()) {
      return { value: (await hit.value) as T, cached: true, at: hit.at };
    }
    const at = this.now();
    const value = load();
    this.makeRoom();
    this.entries.set(key, { expires: at + this.ttlMs, value, at });
    try {
      return { value: await value, cached: false, at };
    } catch (err) {
      if (this.entries.get(key)?.value === value) this.entries.delete(key);
      throw err;
    }
  }

  /** Frees one slot: drop expired entries first, else only the oldest one (never a full clear). */
  private makeRoom(): void {
    if (this.entries.size < this.maxEntries) return;
    const now = this.now();
    for (const [key, entry] of this.entries) {
      if (entry.expires <= now) this.entries.delete(key);
    }
    if (this.entries.size < this.maxEntries) return;
    const oldest = this.entries.keys().next();
    if (!oldest.done) this.entries.delete(oldest.value);
  }
}
