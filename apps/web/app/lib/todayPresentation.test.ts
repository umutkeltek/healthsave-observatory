import { describe, expect, test } from "bun:test";
import type { Finding, MetricSeries, SeriesPoint } from "./api";
import {
  dailyMedians,
  dailyReadings,
  trendWindow,
  recoveryRecency,
  todaySelection,
  todaySelectionUrl,
  sleepDurationFromStages,
  todayFindings,
  todayReadings,
} from "./todayPresentation";

function point(
  value: number,
  t: string,
  source = "watch",
  extra: Partial<SeriesPoint> = {},
): SeriesPoint {
  return {
    value,
    t,
    source_id: source,
    stream_id: source,
    code: null,
    unit: "ms",
    confidence: null,
    ...extra,
  };
}
function series(points: SeriesPoint[]): MetricSeries {
  return {
    metric: {
      id: "vital.hrv_sdnn",
      display_name: "HRV SDNN",
      category: "vital",
      value_type: "quantity",
      canonical_unit: "ms",
    },
    range: "7d",
    start: "2026-10-01",
    end: "2026-10-08",
    points,
  };
}

describe("Today readings", () => {
  test("recovery ages independently of sync, with explicit missing and future-date states", () => {
    const now = Date.parse("2026-10-17T06:00:00Z");
    expect(recoveryRecency("2026-10-17T05:59:00Z", now)).toBe("current");
    expect(recoveryRecency("2026-10-16T06:00:00Z", now)).toBe("older");
    expect(recoveryRecency(null, now)).toBe("unknown");
    expect(recoveryRecency("not-a-date", now)).toBe("unknown");
    expect(recoveryRecency("2026-10-18T00:00:00Z", now)).toBe("unknown");
  });

  test("exploration links restore known metrics and ranges and safely default unknown ones", () => {
    const ids = ["vital.hrv_sdnn", "activity.steps"];
    const href = todaySelectionUrl(
      "http://localhost:4173/?mode=observatory#today-reading-detail",
      "activity.steps",
      7,
    );
    const url = new URL(href, "http://localhost:4173");
    expect(url.searchParams.get("mode")).toBe("observatory");
    expect(url.hash).toBe("#today-reading-detail");
    expect(todaySelection(url.searchParams, ids, ids[0])).toEqual({
      selectedId: "activity.steps",
      range: 7,
    });
    expect(
      todaySelection(
        new URLSearchParams("metric=missing&range=999d"),
        ids,
        ids[0],
      ),
    ).toEqual({ selectedId: "vital.hrv_sdnn", range: 30 });
  });

  test("daily totals keep the latest snapshot instead of adding or averaging it", () => {
    const readings = todayReadings(
      series([
        point(8000, "2026-10-02T12:00:00Z", "watch", {
          aggregation_scope: "owner_all_source_day_total",
        }),
        point(2000, "2026-10-02T01:00:00Z", "watch", {
          aggregation_scope: "owner_all_source_day_total",
        }),
        point(700, "2026-10-02T13:00:00Z", "phone"),
        point(50, "2026-10-03T01:00:00Z", "watch", {
          aggregation_scope: "owner_all_source_day_total",
        }),
      ]),
    );
    expect(dailyReadings(readings)).toEqual([
      { date: "2026-10-02", value: 8000 },
      { date: "2026-10-03", value: 50 },
    ]);
  });

  test("seven-day windows include today and six previous UTC dates, without moving to stale data", () => {
    const days = [
      { date: "2026-10-09", value: 10 },
      { date: "2026-10-10", value: 20 },
      { date: "2026-10-16", value: 30 },
      { date: "2026-10-17", value: 40 },
    ];
    expect(trendWindow(days, 7, "2026-10-16T23:59:00Z")).toEqual(
      days.slice(1, 3),
    );
    expect(trendWindow(days.slice(0, 1), 7, "2026-10-16T01:00:00Z")).toEqual(
      [],
    );
    expect(trendWindow(days.slice(0, 1), 30, "2026-10-16T01:00:00Z")).toEqual(
      days.slice(0, 1),
    );
  });

  test("sorts valid readings and keeps a single source instead of averaging conflicting devices", () => {
    const values = todayReadings(
      series([
        point(60, "2026-10-03T10:00:00Z"),
        point(120, "2026-10-02T10:00:00Z", "ring"),
        point(40, "2026-10-01T10:00:00Z"),
        point(NaN, "2026-10-04T10:00:00Z"),
        point(50, "invalid"),
      ]),
    );
    expect(values.map((p) => p.value)).toEqual([40, 60]);
    expect(todayReadings(null)).toEqual([]);
  });
  test("prefers an explicitly primary stream over the latest competing stream", () => {
    expect(
      todayReadings(
        series([
          point(40, "2026-10-01", "watch", { is_primary: true }),
          point(90, "2026-10-02", "ring"),
        ]),
      ).map((p) => p.value),
    ).toEqual([40]);
  });
  test("uses canonical owner totals without adding their component observations", () => {
    expect(
      todayReadings(
        series([
          point(900, "2026-10-01", "phone"),
          point(300, "2026-10-01", "watch"),
          point(1100, "2026-10-01", "owner", {
            aggregation_scope: "owner_all_source_day_total",
          }),
        ]),
      ).map((p) => p.value),
    ).toEqual([1100]);
  });
  test("daily medians resist an outlier and do not invent missing days", () => {
    const points = todayReadings(
      series([
        point(40, "2026-10-01T01:00:00Z"),
        point(50, "2026-10-01T02:00:00Z"),
        point(900, "2026-10-01T03:00:00Z"),
        point(70, "2026-10-03T01:00:00Z"),
        point(80, "2026-10-03T02:00:00Z"),
      ]),
    );
    expect(dailyMedians(points)).toEqual([
      { date: "2026-10-01", value: 50 },
      { date: "2026-10-03", value: 75 },
    ]);
  });
  test("sleep uses real reconciled intervals and never multiplies overlapping stages", () => {
    const stages = series([
      point(0, "2026-10-01T22:00:00Z", "watch", {
        value: null,
        code: "core",
        interval_end: "2026-10-02T02:00:00Z",
      }),
      point(0, "2026-10-01T22:00:00Z", "phone", {
        value: null,
        code: "asleep",
        interval_end: "2026-10-02T02:00:00Z",
      }),
    ]);
    expect(sleepDurationFromStages(stages)?.points.map((p) => p.value)).toEqual(
      [240],
    );
    expect(
      sleepDurationFromStages(
        series([point(0, "2026-10-01", "watch", { code: "core" })]),
      )?.points,
    ).toEqual([]);
  });
});

test("Today findings show the latest check per metric and kind, with attention first", () => {
  const finding = (
    id: number,
    type: string,
    metric: string,
    created: string,
  ): Finding => ({
    id,
    finding_type: type,
    metric,
    created_at: created,
    severity: null,
    structured_data: {},
    card: null,
    schema_version: 0,
  });
  const selected = todayFindings([
    finding(1, "recovery_score", "recovery", "2026-10-04"),
    finding(2, "trend", "activity.steps", "2026-10-01"),
    finding(3, "trend", "activity.steps", "2026-10-04"),
    finding(4, "anomaly", "vital.resting_heart_rate", "2026-10-03"),
    finding(5, "summary", "sleep.stage", "2026-10-04"),
    finding(6, "summary", "body.weight", "2026-10-04"),
  ]);
  expect(selected[0].id).toBe(4);
  expect(selected.map((f) => f.id)).not.toContain(1);
  expect(selected.map((f) => f.id)).not.toContain(2);
  expect(selected).toHaveLength(3);
});
