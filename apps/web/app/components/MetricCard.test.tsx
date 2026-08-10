import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { MetricSeries } from "../lib/api";

import { MetricCard } from "./MetricCard";

function series(metricId: string, values: number[]): MetricSeries {
  return {
    metric: { id: metricId, display_name: metricId, category: "vital", value_type: "decimal", canonical_unit: null },
    range: "7d",
    start: values.length + "",
    end: values.length + "",
    points: values.map((value, i) => ({
      t: `2026-01-${String(i + 1).padStart(2, "0")}T08:00:00Z`,
      value,
      code: null,
      unit: null,
      source_id: "src",
      stream_id: null,
      confidence: null,
    })),
  };
}

describe("MetricCard directional tone", () => {
  test("a rise in resting HR (lower is better) reads as bad, not good", () => {
    // avg 52.5, last 60 → rising
    const html = renderToStaticMarkup(<MetricCard series={series("vital.resting_heart_rate", [50, 50, 50, 60])} fallbackTitle="" />);
    expect(html).toContain("metric-state bad");
    expect(html).toContain("Higher by");
  });

  test("a drop in resting HR reads as good", () => {
    // avg 57.5, last 50 → falling
    const html = renderToStaticMarkup(<MetricCard series={series("vital.resting_heart_rate", [60, 60, 60, 50])} fallbackTitle="" />);
    expect(html).toContain("metric-state good");
    expect(html).toContain("Lower by");
  });

  test("a rise in HRV (higher is better) reads as good", () => {
    const html = renderToStaticMarkup(<MetricCard series={series("vital.hrv_sdnn", [40, 40, 40, 55])} fallbackTitle="" />);
    expect(html).toContain("metric-state good");
    expect(html).toContain("Higher by");
  });

  test("stays neutral when the metric direction is unknown", () => {
    const html = renderToStaticMarkup(<MetricCard series={series("custom.unknown_metric", [10, 10, 10, 20])} fallbackTitle="" />);
    expect(html).not.toContain("metric-state good");
    expect(html).not.toContain("metric-state bad");
    expect(html).toContain("metric-state\"");
    expect(html).toContain("Higher by");
  });
});
