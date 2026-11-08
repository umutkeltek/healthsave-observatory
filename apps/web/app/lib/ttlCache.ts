// Process-level stale-while-revalidate cache for the backend reads that are
// genuinely expensive (canonical-coverage aggregates run 5-20s cold on a
// 2M-row store). Per-request dedupe stays in React cache(); this layer makes
// the SECOND page view (and every navigation) instant. Semantics per key:
//   - fresh (younger than ttlMs)  → cached value, no fetch
//   - stale, backend healthy      → cached value AT ONCE + one background
//                                   refresh; never blocks the page
//   - miss, or older than MAX_STALE_MS → wait for the fetch
//   - the last fetch failed       → no stale value is served as current: within
//                                   FAILURE_BACKOFF_MS the read fails at once
//                                   (the page shows unreachable) without asking
//                                   the backend again; after it, one blocking
//                                   attempt
// Every fetch is single-flight: concurrent callers share the one in flight.
//
// Honest staleness: a stale value shown while its refresh runs is reported by
// staleRefreshStatus(). The change poll (app/api/changes) passes it to the
// browser, where the live pill says "updating" and the page redraws once the
// refresh has landed (components/LiveStatus.tsx).
//
// Writes drop only the keys they change (invalidateSwr, from lib/api.ts), and a
// fetch that started before a drop cannot put its older answer back.

export const FAILURE_BACKOFF_MS = 5_000;
// Beyond this a cached value is too old to show even while refreshing.
export const MAX_STALE_MS = 24 * 60 * 60_000;

type Entry = {
  value: unknown;
  hasValue: boolean;
  storedAt: number;
  inflight: Promise<unknown> | null;
  failedAt: number | null;
  error: unknown;
};

// One cache per server process, not per bundle: Next bundles route handlers
// (app/api/changes, which clears this cache when the backend changes)
// separately from pages, and each bundle gets its own copy of this module.
// Module-level state would give each its own map, so the change poll would
// clear a cache no page reads. The state lives on globalThis under one key.
type SharedState = {
  entries: Map<string, Entry>;
  // Background refreshes of values that were served stale, still running.
  staleRefreshing: number;
  // When the last of those finished (ms, server clock); 0 = never.
  staleSettledAt: number;
};

const STATE_KEY = Symbol.for("healthsave.web.swrCache");

function shared(): SharedState {
  const holder = globalThis as typeof globalThis & { [STATE_KEY]?: SharedState };
  holder[STATE_KEY] ??= { entries: new Map(), staleRefreshing: 0, staleSettledAt: 0 };
  return holder[STATE_KEY];
}

function fetchInto(state: SharedState, key: string, entry: Entry, fetcher: () => Promise<unknown>, background: boolean) {
  if (background) state.staleRefreshing += 1;
  // An entry dropped (invalidated) while this fetch ran is no longer in the
  // map: its answer predates the drop and is not stored.
  const current = () => state.entries.get(key) === entry;
  const promise: Promise<unknown> = fetcher()
    .then(
      (value) => {
        if (current()) {
          entry.value = value;
          entry.hasValue = true;
          entry.storedAt = Date.now();
          entry.failedAt = null;
          entry.error = undefined;
        }
        return value;
      },
      (error: unknown) => {
        if (current()) {
          entry.failedAt = Date.now();
          entry.error = error;
        }
        throw error;
      },
    )
    .finally(() => {
      if (entry.inflight === promise) entry.inflight = null;
      if (background) {
        state.staleRefreshing -= 1;
        state.staleSettledAt = Date.now();
      }
    });
  entry.inflight = promise;
  // A background refresh has no caller; its failure is recorded on the entry
  // and surfaces on the next read.
  if (background) promise.catch(() => {});
  return promise;
}

export async function swrCache<T>(key: string, ttlMs: number, fetcher: () => Promise<T>): Promise<T> {
  const state = shared();
  const now = Date.now();
  let entry = state.entries.get(key);
  if (!entry) {
    entry = { value: undefined, hasValue: false, storedAt: 0, inflight: null, failedAt: null, error: undefined };
    state.entries.set(key, entry);
  }

  if (entry.failedAt !== null) {
    if (!entry.inflight && now - entry.failedAt < FAILURE_BACKOFF_MS) throw entry.error;
    return (await (entry.inflight ?? fetchInto(state, key, entry, fetcher, false))) as T;
  }

  if (entry.hasValue) {
    const age = now - entry.storedAt;
    if (age < ttlMs) return entry.value as T;
    if (age < MAX_STALE_MS) {
      if (!entry.inflight) fetchInto(state, key, entry, fetcher, true);
      return entry.value as T;
    }
  }

  return (await (entry.inflight ?? fetchInto(state, key, entry, fetcher, false))) as T;
}

/** Stale values being refreshed right now, and when the last such refresh finished. */
export function staleRefreshStatus(): { refreshing: number; settledAt: number } {
  const state = shared();
  return { refreshing: state.staleRefreshing, settledAt: state.staleSettledAt };
}

/**
 * Drop the keys a write changed. A prefix matches the key itself and its
 * per-person ("@owner:…") and parameterised (":…") variants.
 */
export function invalidateSwr(prefixes: readonly string[]): void {
  const { entries } = shared();
  for (const key of [...entries.keys()]) {
    if (prefixes.some((p) => key === p || key.startsWith(`${p}@`) || key.startsWith(`${p}:`))) entries.delete(key);
  }
}

// Dropped by the change poll when the backend's fingerprint moves, and by a
// write that can change any read (the analytical time basis). Also the test seam.
export function clearSwrCache(): void {
  shared().entries.clear();
}
