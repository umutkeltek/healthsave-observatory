// Participant view (migration 029): one Observatory per coach or clinic, one
// key per participant. The shell's switcher stores the chosen person in a
// cookie; api.ts uses these pure helpers to decide, per backend path, whether
// that person's data can be read there.
//
//   scoped  - the server reads that owner when given ?owner= (series, export,
//             sources, devices, streams, readiness, year)
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
  new RegExp(String.raw`^/api/v2/year/[^/?]+${END}`),
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

// Which person this request is about. ONE decision per request, made from the
// cookie AND the server's own owner list; every read, the per-person cache key,
// the write guard and the switcher take it from here, so the name on screen and
// the data under it cannot disagree.
//   primary     - no participant chosen
//   participant - a person the server lists
//   unlisted    - the cookie names someone the server no longer lists: read the
//                 primary person, say so, and clear the cookie
//   unverified  - the owner list could not be read: keep the person that was
//                 chosen, and keep the switcher up so the view stays named
export type ViewedPerson =
  | { kind: "primary" }
  | { kind: "participant"; owner: string }
  | { kind: "unlisted"; requested: string }
  | { kind: "unverified"; owner: string };

type ListedOwner = { id: string; label: string | null; is_default: boolean; active: boolean };

export function resolveViewedPerson(
  cookieOwner: string | null,
  owners: readonly Pick<ListedOwner, "id" | "is_default">[] | null,
): ViewedPerson {
  if (cookieOwner === null) return { kind: "primary" };
  if (owners === null) return { kind: "unverified", owner: cookieOwner };
  const listed = owners.some((owner) => !owner.is_default && owner.id.toLowerCase() === cookieOwner);
  return listed ? { kind: "participant", owner: cookieOwner } : { kind: "unlisted", requested: cookieOwner };
}

/** The owner id reads go to (null = the primary person). */
export function readOwner(person: ViewedPerson): string | null {
  switch (person.kind) {
    case "participant":
    case "unverified":
      return person.owner;
    case "primary":
    case "unlisted":
      return null;
  }
}

export type ParticipantOption = {
  id: string;
  label: string | null;
  isDefault: boolean;
  active: boolean;
};

export type ParticipantNotice = "unlisted" | "unverified" | null;

export type SwitcherModel = {
  /** Empty means no select; otherwise always holds `current` and the primary person. */
  options: ParticipantOption[];
  current: string;
  notice: ParticipantNotice;
  /** The cookie names someone the server does not list: clear it. */
  clearCookie: boolean;
};

const PRIMARY_OPTION: ParticipantOption = { id: DEFAULT_OWNER_ID, label: null, isDefault: true, active: true };

/**
 * What the shell's switcher shows for `person`. The select is shown whenever
 * the cookie scopes reads, even with one listed owner or no list at all.
 */
export function switcherModel(person: ViewedPerson, owners: readonly ListedOwner[] | null): SwitcherModel {
  const scoped = readOwner(person);
  const options: ParticipantOption[] = (owners ?? []).map((owner) => ({
    id: owner.id.toLowerCase(),
    label: owner.label,
    isDefault: owner.is_default,
    active: owner.active,
  }));
  if (scoped !== null && !options.some((option) => option.id === scoped)) {
    options.push({ id: scoped, label: null, isDefault: false, active: true });
  }
  const show = options.length > 1 || scoped !== null;
  if (show && !options.some((option) => option.isDefault)) options.unshift(PRIMARY_OPTION);
  return {
    options: show ? options : [],
    current: scoped ?? DEFAULT_OWNER_ID,
    notice: person.kind === "unlisted" || person.kind === "unverified" ? person.kind : null,
    clearCookie: person.kind === "unlisted",
  };
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
