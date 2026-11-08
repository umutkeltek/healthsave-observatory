// The server's read-cache signal, carried on every /api/changes answer so the
// live pill can be honest about cached values (lib/ttlCache.ts):
//   refreshing - stale values shown on some page are being refreshed now
//   settledAt  - when the last such refresh finished (server clock, ms)
// Client-safe: no server imports.

export const REFRESHING_HEADER = "x-healthsave-refreshing";
export const REFRESHED_AT_HEADER = "x-healthsave-refreshed-at";

export type CacheSignal = { refreshing: number; settledAt: number };

export function cacheSignalHeaders(signal: CacheSignal): Record<string, string> {
  return { [REFRESHING_HEADER]: String(signal.refreshing), [REFRESHED_AT_HEADER]: String(signal.settledAt) };
}

export function readCacheSignal(headers: Headers): CacheSignal | null {
  const refreshing = Number(headers.get(REFRESHING_HEADER));
  const settledAt = Number(headers.get(REFRESHED_AT_HEADER));
  if (headers.get(REFRESHING_HEADER) === null || !Number.isFinite(refreshing) || !Number.isFinite(settledAt)) {
    return null;
  }
  return { refreshing, settledAt };
}

/**
 * What the live pill does after a poll that answered: say "updating" while
 * cached values are being refreshed, and redraw the page once a refresh has
 * landed after the page was rendered (renderedAt, server clock).
 */
export function liveAfterPoll(signal: CacheSignal | null, renderedAt: number): { updating: boolean; redraw: boolean } {
  if (!signal) return { updating: false, redraw: false };
  if (signal.refreshing > 0) return { updating: true, redraw: false };
  return { updating: false, redraw: signal.settledAt > renderedAt };
}
