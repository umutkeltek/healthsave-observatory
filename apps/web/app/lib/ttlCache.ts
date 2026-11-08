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

// One cache per server process, not per bundle: Next bundles route handlers
// (app/api/changes, which clears this cache when the backend changes)
// separately from pages, and each bundle gets its own copy of this module.
// Module-level state would give each its own map, so the change poll would
// clear a cache no page reads. The state lives on globalThis under one key.
type SharedState = {
  entries: Map<string, Entry>;
  // Bumped by clearSwrCache, so an answer fetched before a write is dropped.
  generation: number;
};

const STATE_KEY = Symbol.for("healthsave.web.swrCache");

function shared(): SharedState {
  const holder = globalThis as typeof globalThis & { [STATE_KEY]?: SharedState };
  holder[STATE_KEY] ??= { entries: new Map(), generation: 0 };
  return holder[STATE_KEY];
}

function remember(key: string, value: unknown, fetchedIn: number): void {
  const state = shared();
  if (fetchedIn !== state.generation) return;
  state.entries.set(key, { value, storedAt: Date.now(), refreshing: false, refreshFailed: false });
}

export async function swrCache<T>(key: string, ttlMs: number, fetcher: () => Promise<T>): Promise<T> {
  const now = Date.now();
  const entry = shared().entries.get(key);
  const fetchedIn = shared().generation;

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
  const state = shared();
  state.entries.clear();
  state.generation += 1;
}
