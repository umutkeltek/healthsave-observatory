import { describe, expect, test } from "bun:test";
import { formatValue } from "../../lib/format";
import {
  buildScrubSeries,
  calendarDays,
  compactValue,
  nearestDay,
  scrubAnswer,
  scrubValueText,
  startPress,
  takesHandle,
  TOUCH_SLOP,
  usualBand,
} from "./dayScrub";

const fmt = (value: number) => formatValue(value);

describe("day ruler series", () => {
  test("the window is one slot per UTC calendar day, ending on the given day", () => {
    expect(calendarDays("2026-11-16T22:30:00Z", 3)).toEqual([
      "2026-11-14",
      "2026-11-15",
      "2026-11-16",
    ]);
    expect(calendarDays("2026-11-16", 30)).toHaveLength(30);
  });

  test("a day without a reading stays a gap: no value, no comparison, a dot", () => {
    const series = buildScrubSeries({
      dates: calendarDays("2026-11-06", 3),
      readings: [
        { date: "2026-11-04", value: 60 },
        { date: "2026-11-06", value: 56 },
      ],
      band: [58, 66],
      unit: "ms",
      format: fmt,
    });
    const gap = series.days[1];
    expect(gap.value).toBeNull();
    expect(gap.short).toBeNull();
    expect(gap.position).toBeNull();
    expect(scrubValueText(gap, series.unit)).toBe("No reading, Thu, Nov 5");
    expect(scrubAnswer(gap, series)).toEqual({
      value: "No reading",
      rest: " on Thu, Nov 5. The gap stays a gap.",
    });
    expect(series.initial).toBe(2);
  });

  test("the answer line compares the day with the usual range", () => {
    const series = buildScrubSeries({
      dates: ["2026-11-05"],
      readings: [{ date: "2026-11-05", value: 56 }],
      band: [60, 68],
      unit: "ms",
      format: fmt,
    });
    expect(scrubAnswer(series.days[0], series)).toEqual({
      value: "56 ms",
      rest: " on Thu, Nov 5 · below your usual 60 to 68",
    });
  });

  test("the selected day starts on the latest reading, not on an empty today", () => {
    const series = buildScrubSeries({
      dates: calendarDays("2026-11-16", 5),
      readings: [{ date: "2026-11-13", value: 1 }, { date: "2026-11-14", value: 2 }],
      band: null,
      unit: null,
      format: fmt,
    });
    expect(series.initial).toBe(2);
    expect(series.usual).toBeNull();
  });

  test("only a recent daily total may still be counting", () => {
    const base = { band: [5_000, 9_000] as [number, number], unit: "steps", format: fmt, incompleteLatest: true };
    const recent = buildScrubSeries({
      ...base,
      dates: calendarDays("2026-11-16", 7),
      readings: [{ date: "2026-11-15", value: 8_357 }],
    });
    expect(recent.days[5].note).toBe("latest day, may be incomplete");
    expect(recent.days[5].position).toBeNull();
    const old = buildScrubSeries({
      ...base,
      dates: calendarDays("2026-11-16", 7),
      readings: [{ date: "2026-11-12", value: 8_357 }],
    });
    expect(old.days[2].note).toBeNull();
    expect(old.days[2].position).toBe("inside");
  });

  test("a caller's per-day note follows the comparison", () => {
    const series = buildScrubSeries({
      dates: ["2026-11-05"],
      readings: [{ date: "2026-11-05", value: 480, note: "longest of 2 sleep sessions" }],
      band: [400, 450],
      unit: null,
      format: (v) => `${Math.floor(v / 60)}h ${v % 60}m`,
    });
    expect(scrubAnswer(series.days[0], series).rest).toBe(
      " on Thu, Nov 5 · above your usual 6h 40m to 7h 30m · longest of 2 sleep sessions",
    );
  });

  test("week starts and axis captions", () => {
    const month = buildScrubSeries({
      dates: calendarDays("2026-11-16", 30),
      readings: [],
      band: null,
      unit: null,
      format: fmt,
    });
    const mondays = month.days.filter((day) => day.weekStart).map((day) => day.tick);
    expect(mondays).toEqual(["Oct 19", "Oct 26", "Nov 2", "Nov 9", "Nov 16"]);
    const week = buildScrubSeries({
      dates: calendarDays("2026-11-16", 7),
      readings: [],
      band: null,
      unit: null,
      format: fmt,
    });
    expect(week.days.map((day) => day.tick)).toEqual(["Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Mon"]);
  });

  test("usual range is the middle half, and the handle shortens big numbers", () => {
    expect(usualBand([1, 2, 3, 4, 5])).toEqual([2, 4]);
    expect(usualBand([7])).toBeNull();
    expect(compactValue(8_357, "8,357")).toBe("8.4k");
    expect(compactValue(12_400, "12,400")).toBe("12k");
    expect(compactValue(53.7, "53.7")).toBe("53.7");
  });
});

describe("pointer rules shared by the ruler and the chart", () => {
  const even = (n: number) => Array.from({ length: n }, (_, i) => i / (n - 1));

  test("a press picks the nearest day; past either end takes the end day", () => {
    const xs = even(30);
    expect(nearestDay(xs, 0)).toBe(0);
    expect(nearestDay(xs, 1)).toBe(29);
    expect(nearestDay(xs, 0.49)).toBe(14);
    expect(nearestDay(xs, 0.52)).toBe(15);
    expect(nearestDay(xs, -0.3)).toBe(0);
    expect(nearestDay(xs, 1.4)).toBe(29);
    expect(nearestDay(xs, Number.NaN)).toBe(0);
    expect(nearestDay([], 0.5)).toBe(0);
  });

  test("the chart and the ruler agree on the day under the same fraction", () => {
    // The chart passes its own point positions; a 30-day chart lays them out
    // evenly, exactly as the ruler's ticks.
    const chart = even(30).map((x) => Number((x * 100).toFixed(4)) / 100);
    for (const f of [0.03, 0.31, 0.45, 0.77, 0.98]) {
      expect(nearestDay(chart, f)).toBe(nearestDay(even(30), f));
    }
  });

  test("a mouse or pen press takes the handle at once", () => {
    expect(startPress("mouse", 10, 10).active).toBe(true);
    expect(startPress("pen", 10, 10).active).toBe(true);
    expect(takesHandle(startPress("mouse", 10, 10), 10, 200)).toBe(true);
  });

  test("a finger takes the handle only after a clear sideways move", () => {
    const press = startPress("touch", 100, 100);
    expect(press.active).toBe(false);
    expect(takesHandle(press, 100 + TOUCH_SLOP - 1, 100)).toBe(false); // too small
    expect(takesHandle(press, 100 + TOUCH_SLOP, 100)).toBe(true);
    expect(takesHandle(press, 130, 100)).toBe(true);
    expect(takesHandle(press, 70, 102)).toBe(true); // leftwards too
  });

  test("a vertical swipe never takes the handle, so the page scrolls", () => {
    const press = startPress("touch", 100, 100);
    expect(takesHandle(press, 100, 160)).toBe(false);
    expect(takesHandle(press, 104, 40)).toBe(false);
    expect(takesHandle(press, 120, 130)).toBe(false); // more down than across
    expect(takesHandle(press, 120, 120)).toBe(false); // a diagonal is not sideways
  });
});

