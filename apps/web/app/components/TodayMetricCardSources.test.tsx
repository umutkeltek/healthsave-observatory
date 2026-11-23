import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { MetricSeries } from "../lib/api";
import { TodayMetricCard } from "./TodayMetricCard";

const day = (offset: number, hour: number) =>
  new Date(Date.now() - offset * 86_400_000 - (12 - hour) * 3_600_000).toISOString();

const rhr: MetricSeries = {
  metric: { id: "vital.resting_heart_rate", display_name: "Resting Heart Rate", category: "vital", value_type: "quantity", canonical_unit: "bpm" },
  range: "30d",
  start: day(5, 0),
  end: day(0, 12),
  points: [3, 2, 1].flatMap((d) => [
    { t: day(d, 6), value: 60 + d, code: null, unit: "bpm", source_id: "apple", stream_id: "watch", confidence: null },
    { t: day(d, 7), value: 50 + d, code: null, unit: "bpm", source_id: "whoop", stream_id: "whoop-stream", confidence: null },
  ]),
};

describe("Today card with two devices", () => {
  test("names the device shown and gives the other device's own reading", () => {
    const html = renderToStaticMarkup(
      <TodayMetricCard series={rhr} id="vital.resting_heart_rate" title="Resting heart rate" sourceLabels={{ watch: "Apple Watch", "whoop-stream": "Whoop" }} />,
    );
    expect(html).toContain("Latest · Whoop");
    expect(html).toContain("Also Apple Watch 61 bpm · kept apart, not averaged");
    expect(html).not.toContain("56");
  });

  test("one device: no extra line", () => {
    const one = { ...rhr, points: rhr.points.filter((p) => p.source_id === "apple") };
    const html = renderToStaticMarkup(<TodayMetricCard series={one} id="vital.resting_heart_rate" title="Resting heart rate" />);
    expect(html).not.toContain("kept apart");
    expect(html).toContain("Latest reading");
  });
});
