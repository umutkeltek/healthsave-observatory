// The server's read-cache signal, carried on every /api/changes answer so the
// live pill can be honest about cached values (lib/ttlCache.ts):
//   refreshing - stale values shown on some page are being refreshed now
//   settled    - how many such refreshes have landed (a counter, so no clock
//                step can hide one)
// Client-safe: no server imports.

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
