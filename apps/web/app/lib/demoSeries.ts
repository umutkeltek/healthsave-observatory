import type { Correlation, MetricSeries, MetricSummary, SeriesPoint } from "./api";

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

// ── Relationships demo (fresh clone, no backend) ────────────────────────────
//
// A believable set of persisted correlations plus a deterministic related
// pair for the explorer. Deliberately includes one weak, non-significant row
// (p > 0.05) — the demo must model honesty, not just success.

export const DEMO_RELATE_METRICS: MetricSummary[] = [
  { id: "sleep.duration", display_name: "Sleep Duration", category: "sleep", value_type: "numeric", canonical_unit: "min" },
  { id: "vital.hrv_sdnn", display_name: "Heart Rate Variability", category: "vital", value_type: "numeric", canonical_unit: "ms" },
  { id: "activity.steps", display_name: "Steps", category: "activity", value_type: "numeric", canonical_unit: "count" },
  { id: "vital.resting_heart_rate", display_name: "Resting Heart Rate", category: "vital", value_type: "numeric", canonical_unit: "bpm" },
  { id: "activity.exercise_minutes", display_name: "Exercise Minutes", category: "activity", value_type: "numeric", canonical_unit: "min" },
];

export const DEMO_CORRELATIONS: Correlation[] = [
  {
    metric_a: "sleep.duration",
    metric_b: "vital.hrv_sdnn",
    coefficient: 0.58,
    method: "spearman",
    period_days: 90,
    p_value: 0.006,
    created_at: "2026-06-09T06:10:00Z",
  },
  {
    metric_a: "activity.steps",
    metric_b: "vital.resting_heart_rate",
    coefficient: -0.42,
    method: "pearson",
    period_days: 90,
    p_value: 0.021,
    created_at: "2026-06-09T06:10:00Z",
  },
  {
    metric_a: "activity.exercise_minutes",
    metric_b: "vital.hrv_sdnn",
    coefficient: 0.31,
    method: "pearson",
    period_days: 30,
    p_value: 0.094,
    created_at: "2026-06-09T06:10:00Z",
  },
];

// Two coupled 30-day daily series for the explorer: B follows A's shape at
// ~0.6 strength plus its own deterministic wobble, scaled into a plausible
// range for each metric. No Date.now(); clearly labelled demo where rendered.
export function demoRelatedPair(
  a: MetricSummary,
  b: MetricSummary,
): { a: MetricSeries; b: MetricSeries } {
  const base = Date.parse("2026-05-11T08:00:00Z");
  const scale = (m: MetricSummary): { mid: number; amp: number } => {
    if (m.canonical_unit === "bpm") return { mid: 62, amp: 9 };
    if (m.canonical_unit === "ms") return { mid: 52, amp: 14 };
    if (m.canonical_unit === "count") return { mid: 8200, amp: 2600 };
    return { mid: 420, amp: 70 }; // minutes-ish default
  };
  const sa = scale(a);
  const sb = scale(b);
  const shapeA: number[] = [];
  for (let i = 0; i < 30; i += 1) {
    // Smooth multi-week rhythm + a deterministic wobble, in [-1, 1].
    shapeA.push(0.7 * Math.sin(i * 0.45) + 0.3 * ((((i * 11) % 7) / 3) - 1));
  }
  const mk = (m: MetricSummary, vals: number[]): MetricSeries => ({
    metric: m,
    range: "30d",
    start: new Date(base).toISOString(),
    end: new Date(base + 29 * 86_400_000).toISOString(),
    points: vals.map((v, i) => ({
      t: new Date(base + i * 86_400_000).toISOString(),
      value: Math.round(v),
      code: null,
      unit: m.canonical_unit ?? "",
      source_id: "Demo",
      stream_id: "demo-stream",
      confidence: null,
    })),
  });
  const valsA = shapeA.map((s) => sa.mid + sa.amp * s);
  const valsB = shapeA.map(
    (s, i) => sb.mid + sb.amp * (0.62 * s + 0.38 * (0.9 * Math.sin(i * 1.7 + 2))),
  );
  return { a: mk(a, valsA), b: mk(b, valsB) };
}
