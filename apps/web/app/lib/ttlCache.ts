// Process-level stale-while-revalidate cache for the few backend reads that
// are genuinely expensive (canonical-coverage aggregates run 5-20s on a
// 2M-row store). Semantics:
//   - fresh hit  → cached value, no fetch
//   - stale hit  → cached value IMMEDIATELY + one background refresh
//   - miss       → await the fetch (first request after boot pays once)
// Per-request dedupe stays in React cache(); this layer makes the SECOND
// page view (and every navigation) instant. Single-user dashboard: a value
// up to ttlMs old is indistinguishable from live for these surfaces.
//
// Stale data must not pass for current when the backend is down, so a stale
// value is served only while the backend is still answering:
//   - once a background refresh has failed, the next read waits for the
//     backend (and fails like any other read if it is still down)
//   - past MAX_AGE_FACTOR × ttlMs a value is never served at all
// Every successful write clears the cache (lib/api.ts), and a refresh that
// started before the clear cannot put its older answer back.

type Entry = {
  value: unknown;
  storedAt: number;
  refreshing: boolean;
  refreshFailed: boolean;
};

const MAX_AGE_FACTOR = 10;

const store = new Map<string, Entry>();
// Bumped by clearSwrCache, so an answer fetched before a write is dropped.
let generation = 0;

function remember(key: string, value: unknown, fetchedIn: number): void {
  if (fetchedIn !== generation) return;
  store.set(key, { value, storedAt: Date.now(), refreshing: false, refreshFailed: false });
}

export async function swrCache<T>(key: string, ttlMs: number, fetcher: () => Promise<T>): Promise<T> {
  const now = Date.now();
  const entry = store.get(key);
  const fetchedIn = generation;

  if (entry && !entry.refreshFailed && now - entry.storedAt < ttlMs * MAX_AGE_FACTOR) {
    if (now - entry.storedAt >= ttlMs && !entry.refreshing) {
      entry.refreshing = true;
      void fetcher().then(
        (value) => remember(key, value, fetchedIn),
        () => {
          // The loaders' logging choke point reports the failure on the
          // awaited read that follows.
          entry.refreshing = false;
          entry.refreshFailed = true;
        },
      );
    }
    return entry.value as T;
  }

  const value = await fetcher();
  remember(key, value, fetchedIn);
  return value;
}

// Dropped on every successful backend write, and by the change poll when the
// backend's fingerprint moves. Also the test seam.
export function clearSwrCache(): void {
  store.clear();
  generation += 1;
}
