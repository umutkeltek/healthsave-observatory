import { describe, expect, test } from "bun:test";

import {
  dateRange,
  dayLevel,
  gapSentence,
  gapSummary,
  headlineRange,
  headlineValue,
  limitationSentence,
  maskRuns,
  monthCalendar,
  parseYearParam,
  windowIndex,
} from "./year";
import { yearFixture } from "./yearFixture";

describe("gap wording", () => {
  test("each kind of gap says where it sits, with its dates and length", () => {
    expect(gapSentence({ start: "2025-08-03", end: "2025-08-11", days: 9, kind: "inside" })).toBe(
      "9 days with nothing recorded: Aug 3 – Aug 11.",
    );
    expect(gapSentence({ start: "2025-01-01", end: "2025-04-09", days: 99, kind: "before_first" })).toBe(
      "Nothing yet before Apr 10: Jan 1 – Apr 9, 99 days.",
    );
    expect(gapSentence({ start: "2025-11-20", end: "2025-12-31", days: 42, kind: "after_last" })).toBe(
      "Nothing since Nov 19: Nov 20 – Dec 31, 42 days.",
    );
    expect(gapSentence({ start: "2025-03-05", end: "2025-03-05", days: 1, kind: "inside" })).toBe(
      "1 day with nothing recorded: Mar 5.",
    );
  });

  test("the summary names the longest gap inside the record", () => {
    const heart = yearFixture().families[0];
    expect(gapSummary(heart.gaps)).toBe("One gap: 9 days, Aug 3 – Aug 11.");
    expect(gapSummary([])).toBe("No gaps inside the record.");
  });

  test("dates are calendar days, never shifted by the server's time zone", () => {
    expect(dateRange("2025-12-31", "2025-12-31")).toBe("Dec 31");
    expect(dateRange("2025-01-01", "2025-01-02")).toBe("Jan 1 – Jan 2");
  });
});

describe("shapes", () => {
  test("mask runs cover every day once", () => {
    const runs = maskRuns("1100101");
    expect(runs).toEqual([
      [0, 2, "1"],
      [2, 2, "0"],
      [4, 1, "1"],
      [5, 1, "0"],
      [6, 1, "1"],
    ]);
    expect(runs.reduce((n, [, length]) => n + length, 0)).toBe(7);
  });

  test("day level is relative to the year's fullest day, zero only for nothing", () => {
    expect(dayLevel(0, 4)).toBe(0);
    expect(dayLevel(1, 4)).toBe(1);
    expect(dayLevel(4, 4)).toBe(4);
    expect(dayLevel(1, 1)).toBe(4);
  });

  test("the month calendar marks each day without data as a gap and future days as not yet", () => {
    const summary = yearFixture({ windowEnd: "2025-08-05" });
    const august = monthCalendar(summary, 8).flat();
    const days = august.filter((c) => c.kind === "day");
    expect(days.map((c) => (c.kind === "day" ? c.level : -1))).toEqual([3, 3, 0, 0, 0]);
    expect(august.filter((c) => c.kind === "future")).toHaveLength(26);
    // August 2025 starts on a Friday: four blanks before it (Monday first).
    expect(august.slice(0, 4).every((c) => c.kind === "blank")).toBe(true);
    expect(windowIndex(summary, "2025-08-06")).toBe(-1);
  });
});

describe("numbers and limits", () => {
  const summary = yearFixture();
  const byId = (id: string) => summary.headlines.filter((h) => h.id === id);

  test("record headlines read as counts", () => {
    expect(headlineValue(byId("days_recorded")[0])).toBe(`${summary.days_with_data} of 365 days`);
    expect(headlineValue(byId("sources")[0])).toBe("2 sources");
    expect(headlineValue(byId("longest_gap")[0])).toBe("9 days");
  });

  test("per-source headlines keep their own value and range", () => {
    const [watch, ring] = byId("resting_heart_rate");
    expect(headlineValue(watch)).toBe("56 bpm");
    expect(headlineValue(ring)).toBe("50 bpm");
    expect(headlineRange(watch)).toBe("most days 52–61");
    expect(headlineValue(byId("steps")[0])).toBe("8,440 steps");
  });

  test("limitations are worded from their codes and facts", () => {
    expect(limitationSentence({ code: "time_basis", day: null, count: null }, summary)).toContain(
      "Europe/Istanbul, and each day starts at 04:00",
    );
    expect(limitationSentence({ code: "partial_year", day: "2025-11-07", count: null }, summary)).toContain("Nov 7");
    expect(limitationSentence({ code: "unattributed", day: null, count: 3 }, summary)).toContain("3 days");
  });

  test("a year param is four digits between 1970 and this year", () => {
    const today = new Date(Date.UTC(2026, 10, 7));
    expect(parseYearParam("2026", today)).toBe(2026);
    expect(parseYearParam("2027", today)).toBeNull();
    expect(parseYearParam("1969", today)).toBeNull();
    expect(parseYearParam("20x6", today)).toBeNull();
  });
});
