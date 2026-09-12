import { describe, expect, test } from "bun:test";
import type { MetricSeries, MetricSummary, SeriesPoint, StreamView } from "../../lib/api";
import { buildSourceLabels, shouldUseDemoPatterns, sortCards } from "./DataSections";

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

describe("shouldUseDemoPatterns", () => {
  test("does not substitute demo readings for a successful empty live series", () => {
    expect(shouldUseDemoPatterns(series("empty", []))).toBe(false);
  });

  test("uses labelled demo readings when the live series could not be loaded", () => {
    expect(shouldUseDemoPatterns(null)).toBe(true);
  });
});

describe("buildSourceLabels", () => {
  test("uses the stream integration name instead of exposing the canonical source UUID", () => {
    const sourceId = "a9b1e7e0-0000-4000-8000-000000000001";
    const streamId = "11111111-1111-4111-8111-111111111111";
    const points: SeriesPoint[] = [
      {
        t: "2026-09-11T00:00:00Z",
        value: 42,
        code: null,
        unit: null,
        source_id: sourceId,
        stream_id: streamId,
        confidence: null,
      },
    ];
    const streams: StreamView[] = [
      {
        id: streamId,
        source_plugin_id: "apple-healthkit-ios",
        origin_key: "steven's apple watch",
        device_label: "Steven's Apple Watch",
        first_seen_at: "2026-09-01T00:00:00Z",
        last_seen_at: "2026-09-11T00:00:00Z",
      },
    ];

    expect(buildSourceLabels(points, streams)).toEqual({ [sourceId]: "Apple Health" });
  });

  test("prefers a resolved stream label over legacy rows without stream metadata", () => {
    const sourceId = "a9b1e7e0-0000-4000-8000-000000000001";
    const streamId = "11111111-1111-4111-8111-111111111111";
    const points: SeriesPoint[] = [
      {
        t: "2026-09-10T00:00:00Z",
        value: 41,
        code: null,
        unit: null,
        source_id: sourceId,
        stream_id: streamId,
        confidence: null,
      },
      {
        t: "2026-09-11T00:00:00Z",
        value: 42,
        code: null,
        unit: null,
        source_id: sourceId,
        stream_id: null,
        confidence: null,
      },
    ];
    const streams: StreamView[] = [
      {
        id: streamId,
        source_plugin_id: "apple-healthkit-ios",
        origin_key: "steven's apple watch",
        device_label: "Steven's Apple Watch",
        first_seen_at: "2026-09-01T00:00:00Z",
        last_seen_at: "2026-09-11T00:00:00Z",
      },
    ];

    expect(buildSourceLabels(points, streams)).toEqual({ [sourceId]: "Apple Health" });
  });
});
