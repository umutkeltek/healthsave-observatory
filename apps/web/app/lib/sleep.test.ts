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
  const end = new Date(new Date(t).getTime() + 60_000).toISOString();
  return {
    t,
    interval_end: end,
    code,
    value: 1,
    unit: null,
    source_id: "apple",
    stream_id: null,
    confidence: null,
  };
}

function interval(
  t: string,
  intervalEnd: string,
  code: string,
  streamId = "apple-watch",
): SeriesPoint {
  return {
    t,
    interval_end: intervalEnd,
    code,
    value: null,
    unit: null,
    source_id: "apple",
    stream_id: streamId,
    confidence: null,
  };
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

  it("keeps a contiguous Pacific overnight session together across noon UTC", () => {
    const points = [
      interval("2026-06-02T06:00:00Z", "2026-06-02T10:00:00Z", "core"),
      interval("2026-06-02T10:00:00Z", "2026-06-02T12:00:00Z", "deep"),
      interval("2026-06-02T12:00:00Z", "2026-06-02T14:00:00Z", "rem"),
    ];

    const nights = groupSleepNights(points);

    expect(nights.size).toBe(1);
    expect(nights.get("2026-06-01")).toHaveLength(3);
    expect(deriveNight("2026-06-01", nights.get("2026-06-01")!)?.durationMin).toBe(480);
  });

  it("keeps a nap separated by exactly four hours in a different session", () => {
    const points = [
      interval("2026-06-02T00:00:00Z", "2026-06-02T02:00:00Z", "core"),
      interval("2026-06-02T02:00:00Z", "2026-06-02T04:00:00Z", "deep"),
      interval("2026-06-02T08:00:00Z", "2026-06-02T09:00:00Z", "core"),
    ];

    const nights = groupSleepNights(points);
    const derived = [...nights].map(([key, sessionPoints]) => deriveNight(key, sessionPoints));

    expect(nights.size).toBe(2);
    expect([...nights.values()].map((sessionPoints) => sessionPoints.length)).toEqual([2, 1]);
    expect(derived.map((night) => night?.date)).toEqual(["2026-06-01", "2026-06-01"]);
    expect(derived.map((night) => night?.durationMin)).toEqual([240, 60]);
  });

  it("merges a nap separated by three hours fifty-nine minutes into the night", () => {
    // One second under the four-hour separation rule is intentionally merged.
    // Document the boundary so future drift in SESSION_GAP_MS is caught.
    const points = [
      interval("2026-06-02T00:00:00Z", "2026-06-02T02:00:00Z", "core"),
      interval("2026-06-02T02:00:00Z", "2026-06-02T04:00:00Z", "deep"),
      interval("2026-06-02T07:59:01Z", "2026-06-02T08:59:01Z", "core"),
    ];

    const nights = groupSleepNights(points);

    expect(nights.size).toBe(1);
    expect([...nights.values()][0]).toHaveLength(3);
    expect(deriveNight("2026-06-01", [...nights.values()][0])?.durationMin).toBe(300);
  });

  it("splits a nap separated by four hours and one second into a second session", () => {
    const points = [
      interval("2026-06-02T00:00:00Z", "2026-06-02T02:00:00Z", "core"),
      interval("2026-06-02T02:00:00Z", "2026-06-02T04:00:00Z", "deep"),
      interval("2026-06-02T08:00:01Z", "2026-06-02T09:00:01Z", "core"),
    ];

    const nights = groupSleepNights(points);

    expect(nights.size).toBe(2);
  });

  it("keys a second same-day session with the occurrence suffix", () => {
    // Overnight session plus an afternoon nap on the same calendar date:
    // both sessions fall before noon UTC, both keyed to the previous calendar
    // date, but they must not collide on the same map key.
    const points = [
      interval("2026-06-02T00:00:00Z", "2026-06-02T04:00:00Z", "core"),
      interval("2026-06-02T09:00:00Z", "2026-06-02T10:00:00Z", "core"),
    ];

    const nights = groupSleepNights(points);

    expect(nights.size).toBe(2);
    expect(nights.has("2026-06-01")).toBe(true);
    expect(nights.has("2026-06-01#2")).toBe(true);
    expect([...nights.entries()].map(([key, pts]) => deriveNight(key, pts)?.date)).toEqual([
      "2026-06-01",
      "2026-06-01",
    ]);
  });

  it("keeps a session that crosses a DST spring-forward boundary intact", () => {
    // 2026-03-08 02:00 PT jumps to 03:00 PT (US DST). A session that runs
    // through that wall-clock hour is still one continuous night in UTC and
    // must not be split. Noon-UTC heuristic still pins the bedtime date.
    const points = [
      interval("2026-03-08T05:00:00Z", "2026-03-08T09:00:00Z", "core"),
      interval("2026-03-08T09:00:00Z", "2026-03-08T13:30:00Z", "rem"),
    ];

    const nights = groupSleepNights(points);

    expect(nights.size).toBe(1);
    expect(nights.get("2026-03-07")).toHaveLength(2);
    expect(deriveNight("2026-03-07", nights.get("2026-03-07")!)?.durationMin).toBe(510);
  });
});

describe("deriveNight", () => {
  it("uses the full intervals for the reporter's 8h19m night instead of returning 3h1m", () => {
    const points = [
      interval("2026-08-09T14:20:26.000Z", "2026-08-09T15:20:26.000Z", "core"),
      interval("2026-08-09T15:20:26.000Z", "2026-08-09T16:43:15.339Z", "awake"),
      interval("2026-08-09T16:43:15.339Z", "2026-08-09T17:03:15.339Z", "deep"),
      interval("2026-08-09T17:03:15.339Z", "2026-08-09T17:21:26.000Z", "rem"),
      interval("2026-08-09T17:21:26.000Z", "2026-08-10T00:02:39.000Z", "core"),
    ];

    const nights = groupSleepNights(points);
    expect(nights.size).toBe(1);
    const night = deriveNight("2026-08-09", nights.get("2026-08-09")!);

    expect(night).not.toBeNull();
    expect(night!.durationMin).toBeCloseTo(29_963_661 / 60_000, 8);
    expect(night!.durationMin).not.toBe(181);
    expect(night!.wakeTime).toBe("2026-08-10T00:02:39.000Z");
  });

  it("matches the 495-minute crossing-midnight golden payload", () => {
    const points = [
      interval("2026-04-09T22:30:00.000Z", "2026-04-10T01:00:00.000Z", "core"),
      interval("2026-04-10T01:00:00.000Z", "2026-04-10T02:15:00.000Z", "deep"),
      interval("2026-04-10T02:15:00.000Z", "2026-04-10T06:45:00.000Z", "rem"),
    ];

    const nights = groupSleepNights(points);
    expect(nights.size).toBe(1);
    const night = deriveNight("2026-04-09", nights.get("2026-04-09")!);

    expect(night?.durationMin).toBe(495);
    expect(night?.wakeTime).toBe("2026-04-10T06:45:00.000Z");
    expect(night?.stageMinutes).toEqual({ core: 150, deep: 75, rem: 270 });
  });

  it("uses interval unions and excludes awake and in-bed time from sleep duration", () => {
    const night = deriveNight("2026-06-01", [
      interval("2026-06-01T22:00:00Z", "2026-06-01T23:00:00Z", "core"),
      interval("2026-06-01T22:30:00Z", "2026-06-01T23:30:00Z", "core"),
      interval("2026-06-01T23:30:00Z", "2026-06-02T00:00:00Z", "awake"),
      interval("2026-06-01T22:00:00Z", "2026-06-02T00:30:00Z", "In Bed"),
    ]);

    expect(night?.durationMin).toBe(90);
    expect(night?.trackedMin).toBe(120);
    expect(night?.timeInBedMin).toBe(150);
    expect(night?.stageMinutes.core).toBe(90);
    expect(night?.stageMinutes.awake).toBe(30);
    expect(night?.stageMinutes.in_bed).toBe(150);
    expect(night?.wakeTime).toBe("2026-06-02T00:30:00Z");
    expect(sleepTrends([night!]).efficiencies[0]).toBe(60);
  });

  it("uses the in-bed envelope rather than tracked sleep stages for efficiency", () => {
    const night = deriveNight("2026-06-01", [
      interval("2026-06-01T22:00:00Z", "2026-06-02T01:00:00Z", "in_bed"),
      interval("2026-06-01T22:30:00Z", "2026-06-02T00:30:00Z", "core"),
    ]);

    expect(night?.durationMin).toBe(120);
    expect(night?.trackedMin).toBe(120);
    expect(sleepTrends([night!]).efficiencies[0]).toBeCloseTo((120 / 180) * 100, 8);
    expect(night?.timeInBedMin).toBe(180);
  });

  it("ignores malformed, reversed, and implausibly long intervals", () => {
    const night = deriveNight("2026-06-01", [
      interval("2026-06-01T22:00:00Z", "2026-06-01T23:00:00Z", "core"),
      interval("not-a-date", "2026-06-01T23:30:00Z", "deep"),
      interval("2026-06-02T00:00:00Z", "2026-06-01T23:00:00Z", "rem"),
      interval("2026-06-01T00:00:00Z", "2026-06-03T00:00:01Z", "core"),
    ]);

    expect(night?.durationMin).toBe(60);
    expect(night?.segments).toHaveLength(1);
    expect(groupSleepNights([interval("not-a-date", "also-bad", "core")]).size).toBe(0);
  });

  it("counts identical intervals from multiple streams once", () => {
    const night = deriveNight("2026-06-01", [
      interval("2026-06-01T22:00:00Z", "2026-06-01T23:00:00Z", "core", "watch"),
      interval("2026-06-01T22:00:00Z", "2026-06-01T23:00:00Z", "core", "phone"),
    ]);

    expect(night?.durationMin).toBe(60);
    expect(night?.stageMinutes.core).toBe(60);
    expect(night?.segments).toHaveLength(1);
    expect(night?.streamCount).toBe(2);
  });

  it("keeps a detailed stage when generic asleep overlaps it", () => {
    const night = deriveNight("2026-06-01", [
      interval("2026-06-01T22:00:00Z", "2026-06-01T23:00:00Z", "asleep", "phone"),
      interval("2026-06-01T22:00:00Z", "2026-06-01T23:00:00Z", "core", "watch"),
    ]);

    expect(night?.durationMin).toBe(60);
    expect(night?.trackedMin).toBe(60);
    expect(night?.stageMinutes).toEqual({ core: 60 });
    expect(night?.timeInBedMin).toBe(60);
    expect(night?.segments).toEqual([
      {
        t: "2026-06-01T22:00:00.000Z",
        end: "2026-06-01T23:00:00.000Z",
        durationMin: 60,
        stage: "core",
      },
    ]);
  });

  it("reconciles conflicting stage overlaps into one atomic timeline", () => {
    const night = deriveNight("2026-06-01", [
      interval("2026-06-01T22:00:00Z", "2026-06-01T23:00:00Z", "core", "watch"),
      interval("2026-06-01T22:30:00Z", "2026-06-01T23:30:00Z", "deep", "phone"),
      interval("2026-06-01T23:15:00Z", "2026-06-01T23:45:00Z", "awake", "phone"),
    ]);

    expect(night?.durationMin).toBe(75);
    expect(night?.trackedMin).toBe(105);
    expect(night?.timeInBedMin).toBe(105);
    expect(night?.stageMinutes).toEqual({ core: 30, conflict: 45, deep: 15, awake: 15 });
    expect(Object.values(night!.stageMinutes).reduce((sum, mins) => sum + mins, 0)).toBe(
      night?.trackedMin,
    );
    expect(sleepTrends([night!]).efficiencies[0]).toBeCloseTo((75 / 105) * 100, 8);
  });

  it("rejects nights with less than 60 minutes of asleep intervals", () => {
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

describe("sleepTrends", () => {
  it("preserves efficiency semantics for static nights without tracked union data", () => {
    const [efficiency] = sleepTrends([
      {
        date: "2026-06-01",
        bedtime: "2026-06-01T23:00:00Z",
        wakeTime: "2026-06-02T07:00:00Z",
        durationMin: 480,
        stageMinutes: { core: 420, awake: 60 },
        segments: [],
      },
    ]).efficiencies;

    expect(efficiency).toBe(87.5);
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

  it("carries rounded minutes into the hour", () => {
    expect(durationLabel(479.6)).toBe("8h 0m");
  });
});
