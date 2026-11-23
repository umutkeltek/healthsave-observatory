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

describe("MetricCard without a series", () => {
  // null only ever comes from a read that failed (safeSeries); it used to say
  // "No readings in range yet", as if the backend had answered empty.
  test("a failed read says the API did not answer", () => {
    const html = renderToStaticMarkup(<MetricCard series={null} fallbackTitle="Heart Rate" />);
    expect(html).toContain("did not answer");
    expect(html).not.toContain("No readings in this range yet");
  });

  test("an answered empty series still says there are no readings", () => {
    const html = renderToStaticMarkup(<MetricCard series={series("vital.heart_rate", [])} fallbackTitle="" />);
    expect(html).toContain("No numeric readings in this range.");
  });
});

describe("MetricCard with two devices", () => {
  const twoDevices = (): MetricSeries => {
    const base = series("vital.resting_heart_rate", []);
    const at = (d: number, h: number) => `2026-11-${String(20 + d).padStart(2, "0")}T0${h}:00:00Z`;
    const pt = (value: number, t: string, source_id: string, stream_id: string) => ({
      t, value, code: null, unit: "bpm", source_id, stream_id, confidence: null,
    });
    return {
      ...base,
      metric: { ...base.metric, display_name: "Resting Heart Rate", canonical_unit: "bpm" },
      points: [0, 1, 2].flatMap((d) => [
        pt(60 + d, at(d, 6), "apple", "watch"),
        pt(50 + d, at(d, 7), "whoop", "whoop-stream"),
      ]),
    };
  };

  test("shows each device's own value and mean, never one pooled mean", () => {
    const html = renderToStaticMarkup(
      <MetricCard series={twoDevices()} fallbackTitle="" sourceLabels={{ watch: "Apple Watch", "whoop-stream": "Whoop" }} />,
    );
    expect(html).toContain("2 sources · kept apart");
    expect(html).toContain("Apple Watch mean");
    expect(html).toContain("Whoop mean");
    expect(html).toContain("61"); // Apple Watch mean
    expect(html).toContain("51"); // Whoop mean
    expect(html).not.toContain("range mean");
    expect(html).not.toContain("56"); // the pooled mean of both devices
  });
});
