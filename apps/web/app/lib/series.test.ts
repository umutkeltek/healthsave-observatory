import { describe, expect, test } from "bun:test";
import type { SeriesPoint } from "./api";
import { hasOwnerDailyTotalSemantics, summarizeNumericSeries } from "./series";

function point(t: string, value: number | null): SeriesPoint {
  return {
    t,
    value,
    code: null,
    unit: null,
    source_id: "test",
    stream_id: null,
    confidence: null,
  };
}

describe("summarizeNumericSeries", () => {
  test("uses timestamp order rather than the maximum value", () => {
    const result = summarizeNumericSeries([
      point("2026-07-27T08:00:00Z", 10_000),
      point("2026-07-27T10:00:00Z", 7_500),
      point("2026-07-27T09:00:00Z", 8_000),
    ]);
    expect(result.latest?.value).toBe(7_500);
    expect(result.latest?.t).toBe("2026-07-27T10:00:00Z");
    expect(result.average).toBe(8_500);
  });

  test("ignores null, non-finite, and invalid-timestamp readings", () => {
    const result = summarizeNumericSeries([
      point("2026-07-27T08:00:00Z", null),
      point("invalid", 12),
      point("2026-07-27T09:00:00Z", Number.NaN),
    ]);
    expect(result).toEqual({ latest: null, average: null });
  });
});

describe("hasOwnerDailyTotalSemantics", () => {
  test("recognizes HealthKit all-source day totals without treating raw samples as daily", () => {
    const daily = point("2026-08-09T04:00:00Z", 7_698.1);
    daily.aggregation_scope = "owner_all_source_day_total";

    expect(hasOwnerDailyTotalSemantics([daily])).toBe(true);
    expect(hasOwnerDailyTotalSemantics([point("2026-08-09T04:00:00Z", 72)])).toBe(false);
    expect(hasOwnerDailyTotalSemantics([])).toBe(false);
  });
});
