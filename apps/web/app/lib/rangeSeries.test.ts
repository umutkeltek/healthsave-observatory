// The Library detail's range read, against a stubbed backend: a failed read of
// the requested range must never come back as the all-time series wearing the
// requested range's label. No module mocks (see year/yearPage.test.tsx).
import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import type { MetricSeries } from "./api";
import { safeSeriesForRange } from "./load";
import { rangeSeriesView } from "./ranges";
import { clearSwrCache } from "./ttlCache";

const METRIC = {
  id: "vital.heart_rate",
  display_name: "Heart Rate",
  category: "vital",
  value_type: "numeric",
  canonical_unit: "bpm",
};

function series(range: string, values: number[]): MetricSeries {
  return {
    metric: METRIC,
    range,
    start: "",
    end: "",
    points: values.map((value, i) => ({
      t: `2025-0${i + 1}-01T00:00:00Z`,
      value,
      code: null,
      unit: "bpm",
      source_id: "apple",
      stream_id: null,
      confidence: null,
    })),
  };
}

const realFetch = globalThis.fetch;
let answers: Record<string, () => Response> = {};
let requested: string[] = [];

beforeEach(() => {
  clearSwrCache();
  requested = [];
  answers = {};
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);
    for (const [range, answer] of Object.entries(answers)) {
      if (url.endsWith(`/series?range=${range}`)) return answer();
    }
    return Response.json({ detail: "unexpected" }, { status: 500 });
  }) as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  clearSwrCache();
});

describe("safeSeriesForRange", () => {
  test("a failed read of the requested range is unreachable, not the all-time series", async () => {
    answers = {
      "30d": () => Response.json({ detail: "boom" }, { status: 500 }),
      all: () => Response.json(series("all", [61, 64, 70])),
    };
    const read = await safeSeriesForRange(METRIC.id, "30d");
    expect(read.kind).toBe("unreachable");
  });

  test("an answered but empty range falls back to all time, marked as the fallback", async () => {
    answers = {
      "30d": () => Response.json(series("30d", [])),
      all: () => Response.json(series("all", [61, 64, 70])),
    };
    const read = await safeSeriesForRange(METRIC.id, "30d");
    expect(read.kind).toBe("fallback");
    if (read.kind === "fallback") expect(read.series.range).toBe("all");
  });

  test("a range with readings is the requested series", async () => {
    answers = { "7d": () => Response.json(series("7d", [61, 64])) };
    const read = await safeSeriesForRange(METRIC.id, "7d");
    expect(read.kind).toBe("requested");
    expect(requested.some((url) => url.includes("range=all"))).toBe(false);
  });

  test("an empty range whose all-time read failed does not claim the signal has no data", async () => {
    answers = {
      "30d": () => Response.json(series("30d", [])),
      all: () => Response.json({ detail: "boom" }, { status: 500 }),
    };
    const read = await safeSeriesForRange(METRIC.id, "30d");
    expect(read).toEqual({ kind: "empty", olderData: "unknown" });
  });
});

describe("rangeSeriesView", () => {
  test("the fallback is labelled all time and always disclosed", () => {
    const view = rangeSeriesView({ kind: "fallback", series: series("all", [61, 64, 70]) }, "30d");
    expect(view.windowLabel).toBe("All time");
    expect(view.note).toContain("No readings in the 30 days range");
    expect(view.note).toContain("all 3 available readings");
  });

  test("the requested range keeps its own label and needs no disclosure", () => {
    const view = rangeSeriesView({ kind: "requested", series: series("30d", [61, 64, 70]) }, "30d");
    expect(view.windowLabel).toBe("30 days");
    expect(view.note).toBeNull();
  });

  test("unreachable says the API did not answer and offers no series", () => {
    const view = rangeSeriesView({ kind: "unreachable" }, "30d");
    expect(view.series).toBeNull();
    expect(view.note).toContain("did not answer");
  });
});
