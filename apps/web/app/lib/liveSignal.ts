// The server's read-cache signal, carried on every /api/changes answer so the
// live pill can be honest about cached values (lib/ttlCache.ts):
//   refreshing - stale values shown on some page are being refreshed now
//   settled    - how many such refreshes have landed (a counter, so no clock
//                step can hide one)
// Client-safe: no server imports.

import { type PollState, pollState } from "./session";

export const REFRESHING_HEADER = "x-healthsave-refreshing";
export const REFRESHED_HEADER = "x-healthsave-refreshed";

export type CacheSignal = { refreshing: number; settled: number };

export function cacheSignalHeaders(signal: CacheSignal): Record<string, string> {
  return { [REFRESHING_HEADER]: String(signal.refreshing), [REFRESHED_HEADER]: String(signal.settled) };
}

export function readCacheSignal(headers: Headers): CacheSignal | null {
  const refreshing = Number(headers.get(REFRESHING_HEADER));
  const settled = Number(headers.get(REFRESHED_HEADER));
  if (headers.get(REFRESHING_HEADER) === null || !Number.isFinite(refreshing) || !Number.isFinite(settled)) {
    return null;
  }
  return { refreshing, settled };
}

/**
 * What the live pill does after a poll that answered: say "updating" while
 * cached values are being refreshed, and redraw the page once a refresh has
 * landed since the page was rendered (renderedSettled: the count at render).
 */
export function liveAfterPoll(
  signal: CacheSignal | null,
  renderedSettled: number,
): { updating: boolean; redraw: boolean } {
  if (!signal) return { updating: false, redraw: false };
  if (signal.refreshing > 0) return { updating: true, redraw: false };
  return { updating: false, redraw: signal.settled > renderedSettled };
}

// How often the live pill polls /api/changes (components/LiveStatus.tsx).
export const POLL_MS = 30_000;
// While cached values are being refreshed, and for a short while after the
// page changed, look again soon so "updating" and the redraw follow closely.
export const UPDATING_POLL_MS = 2_000;
// A new page's sections can still be reading (and serving cached values) after
// the URL changed, so one prompt poll is not enough: watch for this long.
export const NAV_WATCH_MS = 10_000;

/**
 * Delay before the next poll, or null for none: a hidden tab does not poll
 * (it polls at once when shown again). Fast while refreshing or just after a
 * navigation (until watchUntil, same clock as now), slow otherwise.
 */
export function nextPollDelay({
  hidden,
  updating,
  now,
  watchUntil,
}: {
  hidden: boolean;
  updating: boolean;
  now: number;
  watchUntil: number;
}): number | null {
  if (hidden) return null;
  return updating || now < watchUntil ? UPDATING_POLL_MS : POLL_MS;
}

export type LiveState = PollState | "updating";

// What the live poll remembers between polls (components/LiveStatus.tsx).
export type PollMemory = {
  etag: string | null;
  wasLive: boolean;
  // Landed-refresh count the shown page was rendered against.
  renderedSettled: number;
  // Fast polling until then (performance.now clock): set by a navigation.
  watchUntil: number;
};

/** A navigation: poll often for NAV_WATCH_MS. */
export function armWatch(memory: PollMemory, now: number): PollMemory {
  return { ...memory, watchUntil: now + NAV_WATCH_MS };
}

/**
 * One poll of /api/changes, answered (status, ETag, cache signal) or not
 * (status null): the pill's state, whether to redraw the page, and the delay
 * before the next poll (null: none, the tab is hidden).
 */
export function afterPoll(
  memory: PollMemory,
  answer: { status: number | null; etag: string | null; signal: CacheSignal | null },
  now: number,
  hidden: boolean,
): { memory: PollMemory; state: LiveState; refresh: boolean; delay: number | null } {
  const next = { ...memory };
  let refresh = false;
  if (answer.status === 200 && answer.etag) {
    if (next.etag && answer.etag !== next.etag) refresh = true;
    next.etag = answer.etag;
  }
  let state: LiveState = pollState(answer.status, next.wasLive);
  let updating = false;
  if (state === "live") {
    next.wasLive = true;
    // Cached values on this page being refreshed: say so, look again soon,
    // and redraw once the refresh has landed.
    const after = liveAfterPoll(answer.signal, next.renderedSettled);
    updating = after.updating;
    if (updating) state = "updating";
    if (after.redraw && answer.signal) {
      refresh = true;
      next.renderedSettled = answer.signal.settled;
    }
  }
  // A redraw this poll causes does not re-arm fast polling: new data arriving
  // faster than the fast window would otherwise keep a tab polling and
  // redrawing every 2 s for as long as it lasts. Only a navigation arms it.
  return {
    memory: next,
    state,
    refresh,
    delay: nextPollDelay({ hidden, updating, now, watchUntil: next.watchUntil }),
  };
}
