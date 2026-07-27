import { describe, expect, test } from "bun:test";
import type { MetricSeries, MetricSummary, SeriesPoint } from "../../lib/api";
import { sortCards } from "./DataSections";

function metric(id: string): MetricSummary {
  return { id, display_name: id, category: "test", value_type: "quantity", canonical_unit: null };
}

function point(t: string, value: number): SeriesPoint {
  return { t, value, code: null, unit: null, source_id: "test", stream_id: null, confidence: null };
}

function series(id: string, points: SeriesPoint[]): MetricSeries {
  return { metric: metric(id), range: "7d", start: "", end: "", points };
}

describe("sortCards", () => {
  test("recent sorts by observation timestamp, not numeric magnitude", () => {
    const olderHigh = { metric: metric("older-high"), series: series("older-high", [point("2026-07-20T00:00:00Z", 10_000)]) };
    const newerLow = { metric: metric("newer-low"), series: series("newer-low", [point("2026-07-27T00:00:00Z", 50)]) };
    expect(sortCards([olderHigh, newerLow], "recent").map((card) => card.metric.id)).toEqual([
      "newer-low",
      "older-high",
    ]);
  });

  test("coverage sorts by finite numeric reading count", () => {
    const sparse = { metric: metric("sparse"), series: series("sparse", [point("2026-07-27T00:00:00Z", 1)]) };
    const dense = {
      metric: metric("dense"),
      series: series("dense", [point("2026-07-20T00:00:00Z", 1), point("2026-07-21T00:00:00Z", 2)]),
    };
    expect(sortCards([sparse, dense], "coverage").map((card) => card.metric.id)).toEqual(["dense", "sparse"]);
  });
});
