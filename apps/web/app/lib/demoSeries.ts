import type { MetricSeries, SeriesPoint } from "./api";

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
