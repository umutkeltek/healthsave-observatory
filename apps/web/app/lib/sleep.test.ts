import { describe, expect, it } from "bun:test";

import {
  bedtimeDelta,
  consistencyScore,
  deriveNight,
  durationLabel,
  groupSleepNights,
  sleepDebt,
  sleepTrends,
  type SleepNight,
} from "./sleep";
import type { SeriesPoint } from "./api";

function sp(t: string, code: string): SeriesPoint {
  return { t, code, value: 1, unit: null, source_id: "apple", stream_id: null, confidence: null };
}

// Build a week of perfectly regular sleep: bed at 23:00, wake at 07:00.
function regularNights(dates: string[]): SleepNight[] {
  return dates.map((date) => ({
    date,
    bedtime: `${date}T23:00:00Z`,
    wakeTime: `${date}T07:00:00Z`, // +1day UTC
    durationMin: 480,
    stageMinutes: { deep: 90, core: 240, rem: 90, awake: 60 },
    segments: [],
  }));
}

describe("groupSleepNights", () => {
  it("groups stages into nights using noon split", () => {
    const points: SeriesPoint[] = [
      sp("2026-06-01T23:00:00Z", "core"),
      sp("2026-06-02T00:30:00Z", "deep"),
      sp("2026-06-02T02:00:00Z", "rem"),
      sp("2026-06-02T04:00:00Z", "core"),
      sp("2026-06-02T06:30:00Z", "awake"),
    ];
    const nights = groupSleepNights(points);
    expect(nights.size).toBe(1);
    expect(nights.get("2026-06-01")).toHaveLength(5);
  });

  it("splits across calendar dates when wake is after noon", () => {
    const points: SeriesPoint[] = [
      sp("2026-06-01T22:00:00Z", "core"),
      sp("2026-06-02T01:00:00Z", "deep"),
      sp("2026-06-02T13:00:00Z", "core"), // afternoon nap — new "night" starts
    ];
    const nights = groupSleepNights(points);
    expect(nights.size).toBe(2);
  });
});

describe("deriveNight", () => {
  it("rejects nights with fewer than 5 segments", () => {
    const points = [
      sp("2026-06-01T23:00:00Z", "core"),
      sp("2026-06-01T23:30:00Z", "core"),
    ];
    expect(deriveNight("2026-06-01", points)).toBeNull();
  });

  it("rejects nights whose raw points have no stage codes", () => {
    const points: SeriesPoint[] = Array.from({ length: 5 }, (_, index) => ({
      ...sp(`2026-06-01T23:0${index}:00Z`, "core"),
      code: null,
    }));
    expect(deriveNight("2026-06-01", points)).toBeNull();
  });

  it("rejects nights shorter than 60 minutes", () => {
    const points = [
      sp("2026-06-01T23:00:00Z", "core"),
      sp("2026-06-01T23:30:00Z", "core"),
      sp("2026-06-01T23:35:00Z", "deep"),
      sp("2026-06-01T23:40:00Z", "rem"),
      sp("2026-06-01T23:45:00Z", "awake"),
    ];
    expect(deriveNight("2026-06-01", points)).toBeNull();
  });

  it("derives a valid 8h night with stages", () => {
    const points: SeriesPoint[] = [];
    // 480 samples at 60s intervals (8h)
    for (let i = 0; i < 480; i++) {
      const t = new Date("2026-06-01T23:00:00Z");
      t.setMinutes(t.getMinutes() + i);
      points.push(sp(t.toISOString(), i < 30 ? "awake" : i < 200 ? "deep" : i < 350 ? "core" : "rem"));
    }
    const night = deriveNight("2026-06-01", points);
    expect(night).not.toBeNull();
    expect(night!.durationMin).toBeGreaterThan(400);
    expect(night!.stageMinutes.awake).toBeGreaterThan(0);
    expect(night!.stageMinutes.deep).toBeGreaterThan(0);
  });
});

describe("consistencyScore", () => {
  it("returns null for fewer than 3 nights", () => {
    const nights = regularNights(["2026-06-01", "2026-06-02"]);
    const trend = sleepTrends(nights);
    expect(consistencyScore(trend)).toBeNull();
  });

  it("scores 100 for perfectly regular sleep", () => {
    const nights = regularNights(["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]);
    const trend = sleepTrends(nights);
    const score = consistencyScore(trend);
    expect(score).toBe(100);
  });

  it("scores lower for variable bedtimes", () => {
    const good = regularNights(["2026-06-01", "2026-06-02", "2026-06-03"]);
    // Drift bedtime later each night
    const variable: SleepNight[] = [
      { ...good[0], bedtime: "2026-06-01T23:00:00Z", wakeTime: "2026-06-02T07:00:00Z" },
      { ...good[1], bedtime: "2026-06-02T01:00:00Z", wakeTime: "2026-06-03T09:00:00Z" },
      { ...good[2], bedtime: "2026-06-03T03:00:00Z", wakeTime: "2026-06-04T11:00:00Z" },
    ];
    const regularScore = consistencyScore(sleepTrends(good));
    const variableScore = consistencyScore(sleepTrends(variable));
    expect(regularScore).toBeGreaterThan(variableScore!);
    expect(variableScore).toBeLessThan(70);
  });

  it("handles schedules that cross midnight correctly", () => {
    // Two nights at 23:00 and one at 01:00 — only 2h apart on the clock
    const crosser: SleepNight[] = [
      { date: "2026-06-01", bedtime: "2026-06-01T23:00:00Z", wakeTime: "2026-06-02T07:00:00Z", durationMin: 480, stageMinutes: { deep: 90, core: 240, rem: 90, awake: 60 }, segments: [] },
      { date: "2026-06-02", bedtime: "2026-06-03T01:00:00Z", wakeTime: "2026-06-03T09:00:00Z", durationMin: 480, stageMinutes: { deep: 90, core: 240, rem: 90, awake: 60 }, segments: [] },
      { date: "2026-06-03", bedtime: "2026-06-03T23:15:00Z", wakeTime: "2026-06-04T07:00:00Z", durationMin: 480, stageMinutes: { deep: 90, core: 240, rem: 90, awake: 60 }, segments: [] },
    ];
    const trend = sleepTrends(crosser);
    const score = consistencyScore(trend);
    // The circular std should treat 23:00 and 01:00 as ~2h apart, not 22h apart.
    // An old linear approach would give ~600 min std; circular about ~70 min avg.
    // Score should be > 50 (reasonable consistency despite the late night).
    expect(score).toBeGreaterThan(50);
  });
});

describe("sleepDebt", () => {
  it("computes cumulative shortfall vs 8h target", () => {
    const nights = [
      { date: "2026-06-01", bedtime: "T23:00Z", wakeTime: "T07:00Z", durationMin: 420, stageMinutes: {}, segments: [] },  // -1h
      { date: "2026-06-02", bedtime: "T23:00Z", wakeTime: "T07:00Z", durationMin: 480, stageMinutes: {}, segments: [] },  // 0
      { date: "2026-06-03", bedtime: "T23:00Z", wakeTime: "T07:00Z", durationMin: 390, stageMinutes: {}, segments: [] },  // -1.5h
    ];
    const trend = sleepTrends(nights);
    expect(sleepDebt(trend)).toBe(3); // 2.5h → 3h rounded
  });

  it("returns 0 when on or above target", () => {
    const nights = [
      { date: "2026-06-01", bedtime: "T23:00Z", wakeTime: "T07:00Z", durationMin: 510, stageMinutes: {}, segments: [] },
    ];
    const trend = sleepTrends(nights);
    expect(sleepDebt(trend)).toBe(0); // -0.5h → 0h rounded
  });
});

describe("bedtimeDelta", () => {
  it("compares clock times without including calendar-day distance", () => {
    const trend = sleepTrends([
      {
        date: "2026-06-01",
        bedtime: "2026-06-01T23:00:00Z",
        wakeTime: "2026-06-02T07:00:00Z",
        durationMin: 480,
        stageMinutes: {},
        segments: [],
      },
      {
        date: "2026-06-02",
        bedtime: "2026-06-02T23:10:00Z",
        wakeTime: "2026-06-03T07:10:00Z",
        durationMin: 480,
        stageMinutes: {},
        segments: [],
      },
      {
        date: "2026-06-03",
        bedtime: "2026-06-03T23:20:00Z",
        wakeTime: "2026-06-04T07:20:00Z",
        durationMin: 480,
        stageMinutes: {},
        segments: [],
      },
    ]);
    expect(bedtimeDelta(trend)).toEqual({ bedDelta: 15, wakeDelta: 15 });
  });

  it("handles a bedtime that crosses midnight", () => {
    const trend = sleepTrends([
      {
        date: "2026-06-01",
        bedtime: "2026-06-01T23:50:00Z",
        wakeTime: "2026-06-02T07:00:00Z",
        durationMin: 430,
        stageMinutes: {},
        segments: [],
      },
      {
        date: "2026-06-02",
        bedtime: "2026-06-03T00:10:00Z",
        wakeTime: "2026-06-03T07:10:00Z",
        durationMin: 420,
        stageMinutes: {},
        segments: [],
      },
    ]);
    expect(bedtimeDelta(trend)).toEqual({ bedDelta: 20, wakeDelta: 10 });
  });
});

describe("durationLabel", () => {
  it("formats hours and minutes", () => {
    expect(durationLabel(485)).toBe("8h 5m");
    expect(durationLabel(60)).toBe("1h 0m");
    expect(durationLabel(90)).toBe("1h 30m");
  });
});
