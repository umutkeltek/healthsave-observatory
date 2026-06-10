// Process-level stale-while-revalidate cache for the few backend reads that
// are genuinely expensive (canonical-coverage aggregates run 5–20s on a
// 2M-row store). Semantics:
//   - fresh hit  → cached value, no fetch
//   - stale hit  → cached value IMMEDIATELY + one background refresh
//   - miss       → await the fetch (first request after boot pays once)
// Per-request dedupe stays in React cache(); this layer makes the SECOND
// page view (and every navigation) instant. Single-user dashboard: a value
// up to ttlMs old is indistinguishable from live for these surfaces.

type Entry = {
  value: unknown;
  storedAt: number;
  refreshing: boolean;
};

const store = new Map<string, Entry>();

export async function swrCache<T>(key: string, ttlMs: number, fetcher: () => Promise<T>): Promise<T> {
  const now = Date.now();
  const entry = store.get(key);

  if (entry) {
    const age = now - entry.storedAt;
    if (age >= ttlMs && !entry.refreshing) {
      entry.refreshing = true;
      void fetcher()
        .then((value) => store.set(key, { value, storedAt: Date.now(), refreshing: false }))
        .catch(() => {
          // Keep serving stale on refresh failure — the loaders' logging
          // choke point reports it on the path that awaited.
          entry.refreshing = false;
        });
    }
    return entry.value as T;
  }

  const value = await fetcher();
  store.set(key, { value, storedAt: Date.now(), refreshing: false });
  return value;
}

// Test seam.
export function clearSwrCache(): void {
  store.clear();
}
