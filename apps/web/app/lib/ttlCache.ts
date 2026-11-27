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
// New data on the backend (the change poll's fingerprint moved) EXPIRES every
// entry instead of deleting it (expireSwrCache): each is served once more at
// once while one background refresh runs, and a fetch already in flight stays
// shared. Writes drop only the keys they change (invalidateSwr, from
// lib/api.ts); a fetch that started before a drop cannot put its older answer
// back, and one that started before an expire lands already expired.

import { cache } from "react";

// Durations (TTL, backoff, max stale age) use the monotonic clock: after the
// wall clock steps back (a VM resume, an NTP correction) a value must not stay
// fresh, nor a failed key keep refusing reads, for as long as the step.
const clock = () => performance.now();

export const FAILURE_BACKOFF_MS = 5_000;
// Keys can come from URLs (/library/<id>, /compare?metric=<id>), so the cache
// is bounded: least recently used keys go first, and a failed read goes as
// soon as its backoff has passed.
export const MAX_SWR_ENTRIES = 500;
// Beyond this a cached value is too old to show even while refreshing.
export const MAX_STALE_MS = 24 * 60 * 60_000;

type Entry = {
  value: unknown;
  hasValue: boolean;
  storedAt: number;
  // The expire epoch the stored value was fetched in; older than the current
  // epoch means the backend changed since: stale, whatever its age.
  epoch: number;
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
  // Bumped by expireSwrCache.
  expireEpoch: number;
  // Entries whose stale value was served while their background refresh runs.
  // A clear empties it: a dropped entry is no longer on any page.
  staleRefreshing: Set<Entry>;
  // How many of those refreshes have landed. A counter, not a time: it is
  // compared across bundles and with the layout's render (LiveStatus), and a
  // wall-clock step must not hide a refresh.
  staleSettled: number;
};

const STATE_KEY = Symbol.for("healthsave.web.swrCache");

function shared(): SharedState {
  const holder = globalThis as typeof globalThis & { [STATE_KEY]?: SharedState };
  holder[STATE_KEY] ??= { entries: new Map(), expireEpoch: 0, staleRefreshing: new Set(), staleSettled: 0 };
  return holder[STATE_KEY];
}

// The landed-refresh count a page render is compared against (the live poll
// redraws once more have landed; components/LiveStatus.tsx). Taken once per
// server request, at the first cache read or when the layout asks, whichever
// comes first: the root layout and the page render in parallel, so a count
// read by the layout later could already include a refresh this page started,
// and that page would never redraw. React's cache() is request-scoped in server
// components; elsewhere it is a plain call, where no mark is rendered.
type RenderScope = { settled: number | null };
const requestScope = cache((): RenderScope => ({ settled: null }));
let testScope: RenderScope | null = null;

function markRender(state: SharedState): number {
  const scope = testScope ?? requestScope();
  scope.settled ??= state.staleSettled;
  return scope.settled;
}

/** The landed-refresh count when this request's render started reading. */
export function renderedSettledMark(): number {
  return markRender(shared());
}

/** Test seam: run fn as one server request render. */
export async function inRenderScopeForTests<T>(fn: () => Promise<T>): Promise<T> {
  testScope = { settled: null };
  try {
    return await fn();
  } finally {
    testScope = null;
  }
}

function fetchInto(state: SharedState, key: string, entry: Entry, fetcher: () => Promise<unknown>, background: boolean) {
  if (background) state.staleRefreshing.add(entry);
  const startedIn = state.expireEpoch;
  // An entry dropped (invalidated) while this fetch ran is no longer in the
  // map: its answer predates the drop and is not stored.
  const current = () => state.entries.get(key) === entry;
  const promise: Promise<unknown> = fetcher()
    .then(
      (value) => {
        if (current()) {
          entry.value = value;
          entry.hasValue = true;
          entry.storedAt = clock();
          entry.epoch = startedIn;
          entry.failedAt = null;
          entry.error = undefined;
        }
        return value;
      },
      (error: unknown) => {
        if (current()) {
          entry.failedAt = clock();
          entry.error = error;
        }
        throw error;
      },
    )
    .finally(() => {
      if (entry.inflight === promise) entry.inflight = null;
      if (background && state.staleRefreshing.delete(entry)) state.staleSettled += 1;
    });
  entry.inflight = promise;
  // A background refresh has no caller; its failure is recorded on the entry
  // and surfaces on the next read.
  if (background) promise.catch(() => {});
  return promise;
}

// Room for one more key: drop failed reads whose backoff has passed, then the
// least recently used keys. A key with a fetch in flight is never dropped.
function makeRoom(state: SharedState, now: number): void {
  for (const [key, entry] of state.entries) {
    if (entry.failedAt !== null && !entry.inflight && now - entry.failedAt >= FAILURE_BACKOFF_MS) {
      state.entries.delete(key);
    }
  }
  for (const [key, entry] of state.entries) {
    if (state.entries.size < MAX_SWR_ENTRIES) break;
    if (!entry.inflight) state.entries.delete(key);
  }
}

export async function swrCache<T>(key: string, ttlMs: number, fetcher: () => Promise<T>): Promise<T> {
  const state = shared();
  markRender(state);
  const now = clock();
  let entry = state.entries.get(key);
  if (entry) {
    // Most recently used last (a Map keeps insertion order).
    state.entries.delete(key);
    state.entries.set(key, entry);
  } else {
    makeRoom(state, now);
    entry = {
      value: undefined,
      hasValue: false,
      storedAt: 0,
      epoch: state.expireEpoch,
      inflight: null,
      failedAt: null,
      error: undefined,
    };
    state.entries.set(key, entry);
  }

  if (entry.failedAt !== null) {
    if (!entry.inflight && now - entry.failedAt < FAILURE_BACKOFF_MS) throw entry.error;
    return (await (entry.inflight ?? fetchInto(state, key, entry, fetcher, false))) as T;
  }

  if (entry.hasValue) {
    const age = now - entry.storedAt;
    if (age < ttlMs && entry.epoch === state.expireEpoch) return entry.value as T;
    if (age < MAX_STALE_MS) {
      if (!entry.inflight) fetchInto(state, key, entry, fetcher, true);
      return entry.value as T;
    }
  }

  return (await (entry.inflight ?? fetchInto(state, key, entry, fetcher, false))) as T;
}

/** Stale values being refreshed right now, and how many such refreshes have landed. */
export function staleRefreshStatus(): { refreshing: number; settled: number } {
  const state = shared();
  return { refreshing: state.staleRefreshing.size, settled: state.staleSettled };
}

/**
 * Drop the keys a write changed. A prefix matches the key itself and its
 * per-person ("@owner:…") and parameterised (":…") variants.
 */
export function invalidateSwr(prefixes: readonly string[]): void {
  const { entries, staleRefreshing } = shared();
  for (const [key, entry] of [...entries]) {
    if (prefixes.some((p) => key === p || key.startsWith(`${p}@`) || key.startsWith(`${p}:`))) {
      entries.delete(key);
      staleRefreshing.delete(entry);
    }
  }
}

/**
 * The backend has new data (the change poll's fingerprint moved): every value
 * is stale from now on. Values stay and are served once more while their
 * refresh runs; fetches in flight stay shared.
 */
export function expireSwrCache(): void {
  shared().expireEpoch += 1;
}

// Drops everything, in-flight fetches included: only for a write that changes
// what every read means (the analytical time basis). Also the test seam.
export function clearSwrCache(): void {
  const state = shared();
  state.entries.clear();
  state.staleRefreshing.clear();
}
