import type { MetricSeries, MetricSummary, SeriesPoint } from "./api";

// A believable demo series for /compare so a fresh clone (no backend) renders
// alive — parallel to DEMO_PROVENANCE. Two sources for the SAME metric (HRV),
// where Apple (SDNN) reads lower than Whoop (RMSSD): the cross-vendor
// non-comparability story, and a later-week decline for the period story.
// Clearly labelled as demo wherever it renders.

const DAYS = [
  "2026-05-27", "2026-05-28", "2026-05-29", "2026-05-30", "2026-05-31", "2026-06-01", "2026-06-02",
  "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-06", "2026-06-07", "2026-06-08", "2026-06-09",
];
const APPLE_HRV = [62, 60, 63, 61, 64, 59, 62, 58, 55, 53, 51, 49, 52, 50];
const WHOOP_HRV = [70, 68, 71, 69, 72, 67, 70, 66, 63, 61, 60, 58, 61, 59];

function points(source: string, vals: number[]): SeriesPoint[] {
  const stream = `demo-${source.toLowerCase().replace(/\s+/g, "-")}`;
  return DAYS.map((d, i) => ({
    t: `${d}T08:00:00Z`,
    value: vals[i],
    code: null,
    unit: "ms",
    source_id: source,
    stream_id: stream,
    confidence: null,
  }));
}

// A generic demo series for the Patterns panels (heatmap / weekday / zones /
// table) so a fresh clone renders them alive for any selected metric. 14 days,
// every 2h, with a daily rhythm (low overnight, midday peak) + a mild weekend
// dip and two sources. Deterministic — no Date.now(). Clearly labelled as demo.
export function demoPatternSeries(metric: MetricSummary): MetricSeries {
  const base = Date.parse("2026-05-27T00:00:00Z");
  const isHr = metric.id.includes("heart_rate") || metric.canonical_unit === "bpm";
  const baseVal = isHr ? 78 : 50;
  const amp = isHr ? 46 : 30;
  const points: SeriesPoint[] = [];
  for (let day = 0; day < 14; day += 1) {
    for (let hour = 0; hour < 24; hour += 2) {
      const ts = base + (day * 24 + hour) * 3_600_000;
      const rhythm = Math.sin(((hour - 6) / 24) * Math.PI * 2); // peak ~14:00
      const weekend = day % 7 >= 5 ? -0.35 : 0;
      const wobble = ((day * 7 + hour) % 5) / 10 - 0.2;
      const value = Math.round(baseVal + amp * (0.5 * rhythm + 0.5) + amp * (weekend + wobble) * 0.4);
      const apple = (day + hour) % 3 !== 0;
      points.push({
        t: new Date(ts).toISOString(),
        value: Math.max(0, value),
        code: null,
        unit: metric.canonical_unit ?? "",
        source_id: apple ? "Apple Watch" : "Whoop",
        stream_id: apple ? "demo-apple-watch" : "demo-whoop",
        confidence: null,
      });
    }
  }
  return {
    metric,
    range: "14d",
    start: new Date(base).toISOString(),
    end: new Date(base + 14 * 24 * 3_600_000).toISOString(),
    points,
  };
}

export const DEMO_COMPARE_SERIES: MetricSeries = {
  metric: {
    id: "vital.hrv_sdnn",
    display_name: "Heart Rate Variability",
    category: "vital",
    value_type: "numeric",
    canonical_unit: "ms",
  },
  range: "14d",
  start: `${DAYS[0]}T08:00:00Z`,
  end: `${DAYS[DAYS.length - 1]}T08:00:00Z`,
  points: [...points("Apple Watch", APPLE_HRV), ...points("Whoop", WHOOP_HRV)],
};
