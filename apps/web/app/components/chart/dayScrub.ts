// Per-day series for the day ruler (DayRuler.tsx). Pure and serializable, so a
// server page can build it and hand it to the client ruler as plain data.
//
// One entry per calendar day in the window, in UTC. A day with no reading
// stays empty: it is never filled, interpolated, or averaged from neighbours.

import { joinUnit } from "../../lib/format";
import { quantile } from "./scale";

const DAY_MS = 86_400_000;

export type ScrubPosition = "above" | "below" | "inside";

export type ScrubDay = {
  date: string; // YYYY-MM-DD, UTC
  label: string; // "Thu, Nov 5"
  tick: string | null; // axis caption under the ruler, if this day gets one
  weekStart: boolean; // Monday: taller tick, week line in the chart
  value: number | null; // the reading, in the series' own units; null is a gap
  short: string | null; // handle text; null when the day has no reading
  exact: string | null; // lens and answer value, without unit
  position: ScrubPosition | null; // against the usual range
  note: string | null; // said after the comparison (e.g. a day still counting)
};

export type ScrubSeries = {
  days: ScrubDay[];
  unit: string; // "" when the value carries its own unit (sleep "7h 4m")
  band: [number, number] | null; // usual range, P25 to P75 of the days shown
  usual: [string, string] | null; // the same range, formatted
  initial: number; // the latest day with a reading
};

const longDay = new Intl.DateTimeFormat("en", {
  weekday: "short",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const shortDay = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const weekday = new Intl.DateTimeFormat("en", {
  weekday: "short",
  timeZone: "UTC",
});

const utc = (date: string) => new Date(`${date.slice(0, 10)}T00:00:00Z`);

// The `count` UTC calendar days that end on `end`'s date, oldest first.
export function calendarDays(end: string, count: number): string[] {
  const last = utc(end).getTime();
  return Array.from({ length: count }, (_, i) =>
    new Date(last - (count - 1 - i) * DAY_MS).toISOString().slice(0, 10),
  );
}

// Your usual range: the middle half (P25 to P75) of the days shown. The same
// quantile BaselineRibbon draws as its band.
export function usualBand(values: number[]): [number, number] | null {
  const finite = values.filter(Number.isFinite);
  if (finite.length < 2) return null;
  const sorted = [...finite].sort((a, b) => a - b);
  return [quantile(sorted, 0.25), quantile(sorted, 0.75)];
}

// The handle is small: 8,357 reads 8.4k there. The lens and the answer line
// carry the exact value.
export function compactValue(value: number, exact: string): string {
  const abs = Math.abs(value);
  if (abs >= 10_000) return `${Math.round(value / 1000)}k`;
  if (abs >= 1_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return exact;
}

export function buildScrubSeries({
  dates,
  readings,
  band,
  unit,
  format,
  incompleteLatest = false,
}: {
  dates: string[];
  // One reading per day; the caller chooses it (never an average across
  // sources). A note travels with the day into the answer line.
  readings: { date: string; value: number; note?: string }[];
  band: [number, number] | null;
  unit: string | null;
  format: (value: number) => string; // exact value without its unit
  incompleteLatest?: boolean; // daily totals: the newest day may still be counting
}): ScrubSeries {
  const byDate = new Map<string, number>();
  const notes = new Map<string, string>();
  for (const reading of readings) {
    if (!Number.isFinite(reading.value)) continue;
    byDate.set(reading.date.slice(0, 10), reading.value);
    if (reading.note) notes.set(reading.date.slice(0, 10), reading.note);
  }
  const daily = dates.length <= 7;
  const latest = dates.reduce((found, date, i) => (byDate.has(date) ? i : found), -1);
  const days = dates.map((date, i): ScrubDay => {
    const day = utc(date);
    const weekStart = day.getUTCDay() === 1;
    const value = byDate.get(date);
    const has = value !== undefined;
    const exact = has ? format(value) : null;
    // Only a recent total can still be counting (a day total is stamped at
    // local midnight, so today's may carry yesterday's UTC date).
    const counting = has && incompleteLatest && i === latest && i >= dates.length - 2;
    return {
      date,
      label: longDay.format(day),
      tick: daily ? weekday.format(day) : weekStart ? shortDay.format(day) : null,
      weekStart,
      value: has ? value : null,
      short: has ? compactValue(value, exact!) : null,
      exact,
      position:
        has && band && !counting
          ? value > band[1]
            ? "above"
            : value < band[0]
              ? "below"
              : "inside"
          : null,
      note: counting ? "latest day, may be incomplete" : (notes.get(date) ?? null),
    };
  });
  return {
    days,
    unit: unit ?? "",
    band,
    usual: band ? [format(band[0]), format(band[1])] : null,
    initial: latest >= 0 ? latest : Math.max(0, dates.length - 1),
  };
}

export function scrubValue(day: ScrubDay, unit: string): string {
  return day.exact === null ? "No reading" : joinUnit(day.exact, unit);
}

// "56 ms, Thu, Nov 5": what the slider announces.
export function scrubValueText(day: ScrubDay, unit: string): string {
  return `${scrubValue(day, unit)}, ${day.label}`;
}

// The answer line under the ruler, split so only the value is set in ink:
// "56 ms" + " on Thu, Nov 5 · below your usual 60 to 68".
export function scrubAnswer(
  day: ScrubDay,
  series: Pick<ScrubSeries, "unit" | "usual">,
): { value: string; rest: string } {
  const value = scrubValue(day, series.unit);
  if (day.exact === null) return { value, rest: ` on ${day.label}. The gap stays a gap.` };
  const usual = series.usual;
  const compared =
    day.position && usual ? ` · ${day.position} your usual ${usual[0]} to ${usual[1]}` : "";
  return { value, rest: ` on ${day.label}${compared}${day.note ? ` · ${day.note}` : ""}` };
}

// ── Pointer rules shared by the ruler and the chart above it ──────────────

export type ScrubPress = { x: number; y: number; active: boolean };

// A mouse or pen press takes the handle at once. A finger does not: it may be
// starting to scroll the page.
export function startPress(pointerType: string, x: number, y: number): ScrubPress {
  return { x, y, active: pointerType !== "touch" };
}

// A finger takes the handle once it has moved clearly sideways: at least
// TOUCH_SLOP px, and more across than down. A vertical swipe never does, so
// the page keeps scrolling and the selected day stays put.
export const TOUCH_SLOP = 6;
export function takesHandle(press: ScrubPress, x: number, y: number): boolean {
  if (press.active) return true;
  const dx = Math.abs(x - press.x);
  return dx >= TOUCH_SLOP && dx > Math.abs(y - press.y);
}

// The day nearest a pointer at fraction `f` (0 to 1) across a box whose days
// sit at the fractions `xs`. A pointer past either end takes the end day.
export function nearestDay(xs: number[], f: number): number {
  if (xs.length === 0) return 0;
  const at = Math.min(1, Math.max(0, Number.isFinite(f) ? f : 0));
  let best = 0;
  for (let i = 1; i < xs.length; i++) {
    if (Math.abs(xs[i] - at) < Math.abs(xs[best] - at)) best = i;
  }
  return best;
}
