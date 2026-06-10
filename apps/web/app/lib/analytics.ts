// Pure analytics over the v2 /series point array — the Grafana-parity math,
// computed client-side on data the existing API already returns (api.ts
// SeriesPoint). No I/O, no fetch, no Date.now(): every function is a
// deterministic reduction of its inputs, mirroring lib/provenance.ts. The
// honesty rule holds here too — a comparison returns A and B and a delta, never
// a single merged value.
//
// This module is the load-bearing core for the filtering / sorting / device /
// comparison work (see docs_private/plans/2026-06-09-grafana-parity-frontend-plan.md).
// It is intentionally standalone — nothing imports it yet.

import type { SeriesPoint } from "./api";

type Valued = SeriesPoint & { value: number };

// Drop null/non-finite values once; everything downstream works on real numbers.
function valued(points: SeriesPoint[]): Valued[] {
  return points.filter((p): p is Valued => p.value !== null && Number.isFinite(p.value));
}

function byTime(a: { t: string }, b: { t: string }): number {
  return a.t < b.t ? -1 : a.t > b.t ? 1 : 0;
}

// ── Grouping / distribution ──────────────────────────────────────────────────

export function groupBySource(points: SeriesPoint[]): Map<string, SeriesPoint[]> {
  const out = new Map<string, SeriesPoint[]>();
  for (const p of points) {
    const arr = out.get(p.source_id);
    if (arr) arr.push(p);
    else out.set(p.source_id, [p]);
  }
  return out;
}

// Group points by device stream (stream_id). Points without a stream_id are
// dropped — they cannot be attributed to a physical emitter. This is the
// per-device axis the v2 series endpoint unlocked.
export function groupByStream(points: SeriesPoint[]): Map<string, SeriesPoint[]> {
  const out = new Map<string, SeriesPoint[]>();
  for (const p of points) {
    if (!p.stream_id) continue;
    const arr = out.get(p.stream_id);
    if (arr) arr.push(p);
    else out.set(p.stream_id, [p]);
  }
  return out;
}

export type SourceCount = { source_id: string; count: number };

// Count per source, sorted desc — the "data sources" distribution panels.
export function distribution(points: SeriesPoint[]): SourceCount[] {
  const counts = new Map<string, number>();
  for (const p of points) counts.set(p.source_id, (counts.get(p.source_id) ?? 0) + 1);
  return [...counts.entries()]
    .map(([source_id, count]) => ({ source_id, count }))
    .sort((a, b) => b.count - a.count || (a.source_id < b.source_id ? -1 : 1));
}

export function topN(points: SeriesPoint[], n: number): SourceCount[] {
  return distribution(points).slice(0, Math.max(0, n));
}

// ── Bucketed aggregation (Grafana time_bucket + avg/max/min/sum) ─────────────

export type Stat = "mean" | "max" | "min" | "sum";

function reduceStat(values: number[], stat: Stat): number {
  if (values.length === 0) return 0;
  if (stat === "max") return Math.max(...values);
  if (stat === "min") return Math.min(...values);
  const sum = values.reduce((a, b) => a + b, 0);
  return stat === "sum" ? sum : sum / values.length;
}

export type Grain = "hour" | "day" | "week";

// Deterministic UTC bucket key for an ISO timestamp (no Date.now()).
function bucketKey(iso: string, grain: Grain): string {
  const d = new Date(iso);
  const y = d.getUTCFullYear();
  const mo = `${d.getUTCMonth() + 1}`.padStart(2, "0");
  const day = `${d.getUTCDate()}`.padStart(2, "0");
  if (grain === "hour") return `${y}-${mo}-${day}T${`${d.getUTCHours()}`.padStart(2, "0")}`;
  if (grain === "day") return `${y}-${mo}-${day}`;
  // week: anchor to the UTC Monday of this date's week.
  const mondayOffset = (d.getUTCDay() + 6) % 7;
  const monday = new Date(d);
  monday.setUTCDate(d.getUTCDate() - mondayOffset);
  const wmo = `${monday.getUTCMonth() + 1}`.padStart(2, "0");
  const wday = `${monday.getUTCDate()}`.padStart(2, "0");
  return `${monday.getUTCFullYear()}-${wmo}-${wday}`;
}

export type Bucket = { t: string; value: number; n: number };

export function bucketBy(points: SeriesPoint[], grain: Grain, stat: Stat): Bucket[] {
  const groups = new Map<string, number[]>();
  for (const p of valued(points)) {
    const key = bucketKey(p.t, grain);
    const arr = groups.get(key);
    if (arr) arr.push(p.value);
    else groups.set(key, [p.value]);
  }
  return [...groups.entries()]
    .map(([t, vals]) => ({ t, value: Number(reduceStat(vals, stat).toFixed(3)), n: vals.length }))
    .sort(byTime);
}

// ── Heart-rate zones (the Grafana heart-zone CASE bucketing, as data) ─────────

export type Zone = { zone: string; label: string; min: number; max: number };

export const HR_ZONES: Zone[] = [
  { zone: "Z1", label: "Recovery", min: 0, max: 113 },
  { zone: "Z2", label: "Aerobic", min: 113, max: 132 },
  { zone: "Z3", label: "Tempo", min: 132, max: 151 },
  { zone: "Z4", label: "Threshold", min: 151, max: 170 },
  { zone: "Z5", label: "Maximum", min: 170, max: Number.POSITIVE_INFINITY },
];

export type ZoneCount = { zone: string; label: string; count: number };

export function hrZoneHistogram(points: SeriesPoint[], zones: Zone[] = HR_ZONES): ZoneCount[] {
  const out = zones.map((z) => ({ zone: z.zone, label: z.label, count: 0 }));
  for (const p of valued(points)) {
    const idx = zones.findIndex((z) => p.value >= z.min && p.value < z.max);
    if (idx >= 0) out[idx].count += 1;
  }
  return out;
}

// ── Day-of-week pivot (0 = Monday … 6 = Sunday, UTC) ─────────────────────────

export type DowCell = { dow: number; label: string; value: number; n: number };

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function dayOfWeekPivot(points: SeriesPoint[], stat: Stat = "mean"): DowCell[] {
  const buckets: number[][] = [[], [], [], [], [], [], []];
  for (const p of valued(points)) {
    const dow = (new Date(p.t).getUTCDay() + 6) % 7;
    buckets[dow].push(p.value);
  }
  return buckets.map((vals, dow) => ({
    dow,
    label: DOW_LABELS[dow],
    value: vals.length ? Number(reduceStat(vals, stat).toFixed(3)) : 0,
    n: vals.length,
  }));
}

// ── Week × hour heatmap (Grafana HR-by-hour, generalized) ────────────────────

export type HeatCell = { dow: number; hour: number; value: number | null; n: number };

// A 7×24 grid (Mon..Sun × 0..23, UTC) of the stat over points — the "when in
// the week" heatmap. Empty cells carry value null (rendered blank).
export function weekHourPivot(points: SeriesPoint[], stat: Stat = "mean"): HeatCell[] {
  const buckets = new Map<string, number[]>();
  for (const p of valued(points)) {
    const d = new Date(p.t);
    const dow = (d.getUTCDay() + 6) % 7;
    const key = `${dow}-${d.getUTCHours()}`;
    const arr = buckets.get(key);
    if (arr) arr.push(p.value);
    else buckets.set(key, [p.value]);
  }
  const cells: HeatCell[] = [];
  for (let dow = 0; dow < 7; dow += 1) {
    for (let hour = 0; hour < 24; hour += 1) {
      const v = buckets.get(`${dow}-${hour}`);
      cells.push({ dow, hour, value: v ? Number(reduceStat(v, stat).toFixed(2)) : null, n: v?.length ?? 0 });
    }
  }
  return cells;
}

// ── Period-over-period comparison (net-new; absent from Grafana) ─────────────

export type Period = { mean: number; n: number; start: string | null; end: string | null };
export type Delta = { abs: number; pct: number | null; direction: "up" | "down" | "flat" };
export type PeriodSplit = { a: Period; b: Period; delta: Delta };

// Split the (time-sorted) points into an earlier half A and a later half B; the
// delta is B vs A. A and B are kept separate — NEVER merged into one number.
export function periodSplit(points: SeriesPoint[]): PeriodSplit {
  const v = valued(points).slice().sort(byTime);
  const mid = Math.floor(v.length / 2);
  const make = (arr: Valued[]): Period => ({
    mean: arr.length ? arr.reduce((s, p) => s + p.value, 0) / arr.length : 0,
    n: arr.length,
    start: arr[0]?.t ?? null,
    end: arr[arr.length - 1]?.t ?? null,
  });
  const a = make(v.slice(0, mid));
  const b = make(v.slice(mid));
  const abs = Number((b.mean - a.mean).toFixed(3));
  const pct = a.mean !== 0 ? Number(((abs / Math.abs(a.mean)) * 100).toFixed(1)) : null;
  const direction: Delta["direction"] = abs > 0 ? "up" : abs < 0 ? "down" : "flat";
  return { a, b, delta: { abs, pct, direction } };
}

// ── Threshold bands (Grafana panel thresholds, ported as data) ───────────────
//
// Coarse adult reference ranges for context only. The product reads against the
// USER's own baseline (per docs/healthResearch) — these never stand in for a
// personal baseline or a diagnosis; the opinion layer consumes them.

export type ThresholdBand = { label: string; min: number; max: number; tone: "ok" | "warn" | "down" };

export const THRESHOLDS: Record<string, ThresholdBand[]> = {
  "vital.resting_heart_rate": [
    { label: "low", min: 0, max: 50, tone: "warn" },
    { label: "typical", min: 50, max: 70, tone: "ok" },
    { label: "elevated", min: 70, max: 1000, tone: "down" },
  ],
  "vital.hrv_sdnn": [
    { label: "low", min: 0, max: 30, tone: "down" },
    { label: "moderate", min: 30, max: 60, tone: "warn" },
    { label: "high", min: 60, max: 1000, tone: "ok" },
  ],
  "vital.blood_oxygen": [
    { label: "low", min: 0, max: 95, tone: "down" },
    { label: "normal", min: 95, max: 101, tone: "ok" },
  ],
  "activity.steps": [
    { label: "low", min: 0, max: 5000, tone: "warn" },
    { label: "active", min: 5000, max: 10000, tone: "ok" },
    { label: "high", min: 10000, max: 1_000_000_000, tone: "ok" },
  ],
};

export function classify(metricId: string, value: number): ThresholdBand | null {
  const bands = THRESHOLDS[metricId];
  if (!bands) return null;
  return bands.find((b) => value >= b.min && value < b.max) ?? null;
}

// ── Divergence (the never-average rule, quantified) ────────────────────
//
// When two sources stream the same metric we never merge them; this measures
// HOW MUCH they currently disagree so the UI can say "kept separate — and
// right now they differ by ~12%" instead of a vague caveat.

export type SourceDivergence = {
  diverged: boolean;
  gapPct: number | null; // relative gap between the most-distant source means
  sources: string[];
};

const DIVERGENCE_MIN_POINTS = 3; // per source, before we claim anything
const DIVERGENCE_THRESHOLD_PCT = 10;

export function detectDivergence(points: SeriesPoint[]): SourceDivergence {
  const bySource = groupBySource(points);
  const means: { source: string; mean: number }[] = [];
  for (const [source, pts] of bySource) {
    const values = pts.map((p) => p.value).filter((v): v is number => v !== null);
    if (values.length < DIVERGENCE_MIN_POINTS) continue;
    means.push({ source, mean: values.reduce((a, b) => a + b, 0) / values.length });
  }
  if (means.length < 2) {
    return { diverged: false, gapPct: null, sources: means.map((m) => m.source) };
  }
  const sorted = [...means].sort((a, b) => a.mean - b.mean);
  const low = sorted[0];
  const high = sorted[sorted.length - 1];
  const mid = (Math.abs(low.mean) + Math.abs(high.mean)) / 2 || 1;
  const gapPct = (Math.abs(high.mean - low.mean) / mid) * 100;
  return {
    diverged: gapPct >= DIVERGENCE_THRESHOLD_PCT,
    gapPct,
    sources: means.map((m) => m.source),
  };
}
