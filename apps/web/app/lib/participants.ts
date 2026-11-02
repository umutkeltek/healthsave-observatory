// Participant view (migration 029): one Observatory per coach or clinic, one
// key per participant. The shell's switcher stores the chosen person in a
// cookie; api.ts uses these pure helpers to decide, per backend path, whether
// that person's data can be read there.
//
//   scoped  - the server reads that owner when given ?owner= (series, export,
//             sources, devices, streams, readiness)
//   neutral - not one person's data (catalog, meta, the owner list, the host's
//             egress posture and narrator settings, the change fingerprint)
//   primary - analysis and records that exist only for the primary person
//             (findings, briefs, experiments, moments, receipts, settings).
//             While a participant is selected these are not shown at all, so
//             the coach's findings never sit next to an athlete's charts.

export const PARTICIPANT_COOKIE = "participant";
export const DEFAULT_OWNER_ID = "00000000-0000-0000-0000-000000000001";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type OwnerScope = "scoped" | "neutral" | "primary";

const END = String.raw`(?:\?|$)`;
const SCOPED: readonly RegExp[] = [
  new RegExp(String.raw`^/api/v2/metrics/[^/?]+/series${END}`),
  new RegExp(String.raw`^/api/v2/series${END}`),
  new RegExp(String.raw`^/api/v2/export(?:/metrics)?${END}`),
  new RegExp(String.raw`^/api/v2/(?:sources|devices|streams)${END}`),
  new RegExp(String.raw`^/api/v2/streams/[^/?]+${END}`),
  new RegExp(String.raw`^/api/v2/readiness${END}`),
];
const NEUTRAL: readonly RegExp[] = [
  new RegExp(String.raw`^/api/v2/metrics${END}`),
  new RegExp(String.raw`^/api/v2/meta${END}`),
  new RegExp(String.raw`^/api/v2/owners${END}`),
  new RegExp(String.raw`^/api/v2/privacy${END}`),
  new RegExp(String.raw`^/api/v2/intelligence(?:/[^?]*)?${END}`),
  new RegExp(String.raw`^/api/v2/changes${END}`),
];

/** The selected participant's owner id, or null for the primary person. */
export function parseOwnerCookie(raw: string | null | undefined): string | null {
  const value = (raw ?? "").trim().toLowerCase();
  if (!UUID_RE.test(value) || value === DEFAULT_OWNER_ID) return null;
  return value;
}

export function ownerScope(path: string): OwnerScope {
  if (SCOPED.some((re) => re.test(path))) return "scoped";
  if (NEUTRAL.some((re) => re.test(path))) return "neutral";
  return "primary";
}

export function withOwner(path: string, owner: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}owner=${encodeURIComponent(owner)}`;
}

/**
 * The path to read for `owner` (null = primary person), or null when that path
 * only exists for the primary person and must not be shown in this view.
 */
export function scopePath(path: string, owner: string | null): string | null {
  if (owner === null) return path;
  const scope = ownerScope(path);
  if (scope === "scoped") return withOwner(path, owner);
  if (scope === "neutral") return path;
  return null;
}

/** Process-cache key that never lets one person's cached answer serve another. */
export function ownerCacheKey(key: string, owner: string | null): string {
  return owner === null ? key : `${key}@owner:${owner}`;
}

export const PRIMARY_ONLY = "primary_only";
