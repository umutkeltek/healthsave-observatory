import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { MobilityCard } from "./MobilityCard";
import type { MetricSeries } from "../lib/api";

function makeSeries(metricId: string, points: { t: string; value: number | null }[]): MetricSeries {
  return {
    metric: {
      id: metricId,
      display_name: metricId,
      category: "vital",
      value_type: "quantity",
      canonical_unit: null,
    },
    range: "7d",
    start: "2026-07-20T00:00:00Z",
    end: "2026-07-27T00:00:00Z",
    points: points.map((p) => ({
      t: p.t,
      value: p.value,
      code: null,
      unit: null,
      source_id: null,
      stream_id: null,
      confidence: null,
      semantic_key: null,
      aggregation_scope: null,
      is_primary: true,
    })),
  };
}

describe("MobilityCard", () => {
  test("renders an empty card when no series has data", () => {
    const html = renderToStaticMarkup(
      <MobilityCard
        seriesByMetric={{
          "vital.walking_heart_rate_average": null,
          "mobility.walking_speed": null,
          "mobility.walking_step_length": null,
          "mobility.walking_asymmetry": null,
        }}
      />,
    );
    expect(html).toContain("Walking");
    expect(html).toContain("No walking data yet");
  });

  test("renders the latest value for each walking metric", () => {
    const html = renderToStaticMarkup(
      <MobilityCard
        seriesByMetric={{
          "vital.walking_heart_rate_average": makeSeries("vital.walking_heart_rate_average", [
            { t: "2026-07-22T10:00:00Z", value: 72 },
            { t: "2026-07-25T18:00:00Z", value: 81 },
          ]),
          "mobility.walking_speed": makeSeries("mobility.walking_speed", [
            { t: "2026-07-25T18:00:00Z", value: 1.42 },
          ]),
          "mobility.walking_step_length": makeSeries("mobility.walking_step_length", [
            { t: "2026-07-25T18:00:00Z", value: 76.5 },
          ]),
          "mobility.walking_asymmetry": makeSeries("mobility.walking_asymmetry", [
            { t: "2026-07-25T18:00:00Z", value: 2.1 },
          ]),
        }}
      />,
    );
    expect(html).toContain("Walking HR");
    expect(html).toContain("81 bpm");
    expect(html).toContain("Speed");
    expect(html).toContain("1.4 m/s");
    expect(html).toContain("Step length");
    expect(html).toContain("76.5 cm");
    expect(html).toContain("Asymmetry");
    expect(html).toContain("2.1%");
  });

  test("treats missing walking-HR data without crashing the rest of the card", () => {
    const html = renderToStaticMarkup(
      <MobilityCard
        seriesByMetric={{
          "vital.walking_heart_rate_average": null,
          "mobility.walking_speed": makeSeries("mobility.walking_speed", [
            { t: "2026-07-25T18:00:00Z", value: 1.4 },
          ]),
          "mobility.walking_step_length": null,
          "mobility.walking_asymmetry": null,
        }}
      />,
    );
    expect(html).toContain("1.4 m/s");
    expect(html).toContain("—");
  });
});
