// Year in Health presentation: pure helpers that turn the engine's facts
// (server/api/v2_year.py) into words and shapes. Nothing here computes a health
// number; it only formats what the API returned.

import type {
  YearConfidence,
  YearDeviceChange,
  YearGap,
  YearHeadline,
  YearInHealth,
  YearLimitation,
  YearMonth,
  YearWithheld,
} from "./api";

export const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;
export const MONTH_SHORT = MONTH_NAMES.map((name) => name.slice(0, 3));
export const MONTH_INITIALS = MONTH_NAMES.map((name) => name[0]);

const MS_PER_DAY = 86_400_000;

// ISO dates (YYYY-MM-DD) are calendar days already; parse them as UTC so the
// server's time zone never shifts a day.
function utcDate(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

export function isoAdd(iso: string, days: number): string {
  return new Date(utcDate(iso).getTime() + days * MS_PER_DAY).toISOString().slice(0, 10);
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((utcDate(toIso).getTime() - utcDate(fromIso).getTime()) / MS_PER_DAY);
}

/** "Aug 3" */
export function shortDate(iso: string): string {
  const d = utcDate(iso);
  return `${MONTH_SHORT[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

/** "Aug 3 – Aug 11", or "Aug 3" for one day. */
export function dateRange(start: string, end: string): string {
  return start === end ? shortDate(start) : `${shortDate(start)} – ${shortDate(end)}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

/** Days in the calendar year (365 or 366). */
export function daysInYear(year: number): number {
  return daysBetween(`${year}-01-01`, `${year + 1}-01-01`);
}

export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Index of a date inside the summary's window, or -1 outside it. */
export function windowIndex(summary: Pick<YearInHealth, "window_start" | "days_in_window">, iso: string): number {
  const i = daysBetween(summary.window_start, iso);
  return i >= 0 && i < summary.days_in_window ? i : -1;
}

// Coverage level of one day: 0 = nothing, 1..4 = share of this year's
// largest day (in kinds of data recorded). Relative on purpose: the view
// shows the shape of the year, not a score.
export function dayLevel(count: number, maxCount: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0 || maxCount <= 0) return 0;
  const share = count / maxCount;
  if (share > 0.75) return 4;
  if (share > 0.5) return 3;
  if (share > 0.25) return 2;
  return 1;
}

export type CalendarCell =
  | { kind: "blank" }
  | { kind: "future"; iso: string }
  | { kind: "day"; iso: string; level: number; families: number };

/** One month as week rows (Monday first) for the mini calendar. */
export function monthCalendar(summary: YearInHealth, month: number): CalendarCell[][] {
  const year = summary.year;
  const first = new Date(Date.UTC(year, month - 1, 1));
  const offset = (first.getUTCDay() + 6) % 7; // Monday = 0
  const total = daysInMonth(year, month);
  const maxCount = Math.max(0, ...summary.day_family_counts);
  const cells: CalendarCell[] = Array.from({ length: offset }, () => ({ kind: "blank" }) as const);
  for (let day = 1; day <= total; day++) {
    const iso = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const i = windowIndex(summary, iso);
    if (i < 0) {
      cells.push({ kind: "future", iso });
      continue;
    }
    const families = summary.day_family_counts[i] ?? 0;
    cells.push({ kind: "day", iso, families, level: dayLevel(families, maxCount) });
  }
  while (cells.length % 7 !== 0) cells.push({ kind: "blank" });
  const weeks: CalendarCell[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

/** Consecutive runs of one character in a mask: [startIndex, length, char]. */
export function maskRuns(mask: string): Array<[number, number, string]> {
  const runs: Array<[number, number, string]> = [];
  let i = 0;
  while (i < mask.length) {
    let j = i;
    while (j + 1 < mask.length && mask[j + 1] === mask[i]) j++;
    runs.push([i, j - i + 1, mask[i]]);
    i = j + 1;
  }
  return runs;
}

export function gapSentence(gap: YearGap): string {
  const span = dateRange(gap.start, gap.end);
  switch (gap.kind) {
    case "before_first":
      return `Nothing yet before ${shortDate(isoAdd(gap.end, 1))}: ${span}, ${plural(gap.days, "day")}.`;
    case "after_last":
      return `Nothing since ${shortDate(isoAdd(gap.start, -1))}: ${span}, ${plural(gap.days, "day")}.`;
    case "no_data":
      return `Nothing recorded: ${span}, ${plural(gap.days, "day")}.`;
    default:
      return `${plural(gap.days, "day")} with nothing recorded: ${span}.`;
  }
}

export function insideGaps(gaps: YearGap[]): YearGap[] {
  return gaps.filter((gap) => gap.kind === "inside");
}

export function longestGap(gaps: YearGap[]): YearGap | null {
  return insideGaps(gaps).reduce<YearGap | null>((best, gap) => (best && best.days >= gap.days ? best : gap), null);
}

export function gapSummary(gaps: YearGap[]): string {
  const inside = insideGaps(gaps);
  if (inside.length === 0) {
    return gaps.some((gap) => gap.kind === "no_data") ? "Nothing recorded this year." : "No gaps inside the record.";
  }
  const longest = longestGap(gaps)!;
  if (inside.length === 1) return `One gap: ${plural(longest.days, "day")}, ${dateRange(longest.start, longest.end)}.`;
  return `${inside.length} gaps; the longest is ${plural(longest.days, "day")}, ${dateRange(longest.start, longest.end)}.`;
}

export const CONFIDENCE_LABEL: Record<YearConfidence, string> = {
  ok: "",
  low: "Low confidence",
  none: "No data",
  future: "Not yet",
};

export function monthCoverage(month: YearMonth): string {
  if (month.days === 0) return "not yet";
  return `${month.days_with_data}/${month.days}`;
}

export function changeSentence(change: YearDeviceChange): string {
  return change.kind === "first_seen"
    ? `${change.label}: first reading ${shortDate(change.day)}`
    : `${change.label}: last reading ${shortDate(change.day)}`;
}

function formatNumber(value: number, unit: string | null): string {
  const rounded = unit === "steps" ? Math.round(value / 10) * 10 : Math.round(value);
  return rounded.toLocaleString("en-US");
}

/** "56 bpm" for a per-source median; "312 of 311 days" style for counts. */
export function headlineValue(headline: YearHeadline): string {
  switch (headline.id) {
    case "days_recorded":
      return `${headline.value.toLocaleString("en-US")} of ${(headline.of_days ?? 0).toLocaleString("en-US")} days`;
    case "sources":
      return plural(headline.value, "source");
    case "longest_gap":
      return headline.value === 0 ? "none" : plural(headline.value, "day");
    default:
      return `${formatNumber(headline.value, headline.unit)} ${headline.unit ?? ""}`.trim();
  }
}

export function headlineRange(headline: YearHeadline): string | null {
  if (headline.low === null || headline.high === null) return null;
  return `most days ${formatNumber(headline.low, headline.unit)}–${formatNumber(headline.high, headline.unit)}`;
}

export function isPerSource(headline: YearHeadline): boolean {
  return headline.basis === "median_one_source";
}

export function withheldSentence(item: YearWithheld): string {
  const who = item.source_label ?? "One source";
  return `${item.label}, ${who}: ${plural(item.days, "day")} this year, too few for a number (needs 7).`;
}

export function limitationSentence(item: YearLimitation, summary: YearInHealth): string {
  switch (item.code) {
    case "time_basis":
      return `Days are counted in ${summary.time_zone}, and each day starts at ${summary.day_boundary}. Change this in Settings.`;
    case "day_presence_only":
      return "A day counts as recorded when it holds at least one reading of that kind. It says nothing about how complete the day is.";
    case "partial_year":
      return `The year is not over: this view runs to ${item.day ? shortDate(item.day) : "today"}.`;
    case "record_starts_late":
      return `This record starts on ${item.day ? shortDate(item.day) : "a later day"}. Earlier days are shown as "nothing yet", not as gaps.`;
    case "no_data":
      return "There is no data for this year on this Observatory.";
    case "device_labels":
      return "Devices are told apart by the name the phone reports. A renamed device looks like a new one.";
    case "unattributed":
      return `${plural(item.count ?? 0, "day")} hold readings with no device attached. They count as data, not as a source.`;
    case "derived_excluded":
      return "Values the Observatory derives from other data (scores, ratios) are not counted as recorded days.";
    case "headline_thin":
      return "Some headline numbers rest on few days. They are marked low confidence, or left out.";
    default:
      return item.code;
  }
}

/** Every source's colour slot (1..6), stable by order of appearance. */
export function sourceSlot(order: string[], streamId: string): number {
  const i = order.indexOf(streamId);
  return i < 0 ? 0 : (i % 6) + 1;
}

/** Years to offer around the one shown: the one before and, if begun, the one after. */
export function neighbourYears(year: number, today: Date = new Date()): { previous: number; next: number | null } {
  return { previous: year - 1, next: year + 1 <= today.getUTCFullYear() ? year + 1 : null };
}

/** A year the API can answer for: 1970..this year. */
export function parseYearParam(raw: string, today: Date = new Date()): number | null {
  if (!/^\d{4}$/.test(raw)) return null;
  const year = Number(raw);
  return year >= 1970 && year <= today.getUTCFullYear() ? year : null;
}
