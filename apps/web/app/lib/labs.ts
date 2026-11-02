// Labs presentation - pure helpers for the Labs page. Every number here was
// computed by the server's statistical engine (band, change, gaps); this file
// only words and places it. Copy rule: "outside the lab's range", never a
// diagnosis, never a population "optimal" range.

import type { LabAssessment, LabBand, LabGap, LabMarker, LabResult } from "./api";

const MONTH_DAY_YEAR: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", year: "numeric" };

export function labDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { ...MONTH_DAY_YEAR, timeZone: "UTC" });
}

export function labNumber(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 100) return String(Math.round(value * 10) / 10);
  if (abs >= 10) return String(Math.round(value * 100) / 100);
  return String(Math.round(value * 1000) / 1000);
}

export function labValue(result: Pick<LabResult, "value" | "comparator" | "display_unit">): string {
  return `${result.comparator ?? ""}${labNumber(result.value)} ${result.display_unit}`.trim();
}

export function labRange(result: Pick<LabResult, "reference_low" | "reference_high" | "display_unit">): string {
  const { reference_low: low, reference_high: high } = result;
  if (low != null && high != null) return `${labNumber(low)}–${labNumber(high)} ${result.display_unit}`;
  if (high != null) return `up to ${labNumber(high)} ${result.display_unit}`;
  if (low != null) return `from ${labNumber(low)} ${result.display_unit}`;
  return "no range printed";
}

export const BAND_LABEL: Record<LabBand, string> = {
  below: "Below the lab's range",
  within: "Within the lab's range",
  above: "Above the lab's range",
  no_range: "No range printed",
  censored: "Reported as a limit",
};

// Short form for chips and gap lines.
export const BAND_SHORT: Record<LabBand, string> = {
  below: "below its range",
  within: "within its range",
  above: "above its range",
  no_range: "no range",
  censored: "a limit",
};

export type BandTone = "ok" | "out" | "none";

export function bandTone(band: LabBand): BandTone {
  if (band === "below" || band === "above") return "out";
  if (band === "within") return "ok";
  return "none";
}

function signed(value: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${labNumber(Math.abs(value))}`;
}

// "Down 5 ng/mL (−20.8%) since Sep 8, 2026" plus the cross-lab caveat.
export function changeSentence(assessment: LabAssessment, unit: string): string {
  if (assessment.change == null || assessment.direction == null) {
    if (assessment.change_withheld === "first result") return "First result for this marker.";
    return `No change shown: ${assessment.change_withheld ?? "not comparable"}.`;
  }
  const verb = assessment.direction === "up" ? "Up" : assessment.direction === "down" ? "Down" : "No change";
  const since = assessment.previous_specimen_at ? ` since ${labDate(assessment.previous_specimen_at)}` : "";
  const pct = assessment.change_pct != null ? ` (${signed(assessment.change_pct)}%)` : "";
  const amount = assessment.direction === "flat" ? "" : ` ${labNumber(Math.abs(assessment.change))} ${unit}${pct}`;
  const otherLab = assessment.previous_from_other_lab ? "; the earlier result is from another lab" : "";
  return `${verb}${amount}${since}${otherLab}.`;
}

export function historySentence(assessment: LabAssessment, unit: string): string | null {
  const { versus_history: position, prior_min: lo, prior_max: hi } = assessment;
  if (position == null || lo == null || hi == null) return null;
  const range = `${labNumber(lo)}–${labNumber(hi)} ${unit}`;
  if (position === "below_prior_range") return `Lower than every earlier result (${range}).`;
  if (position === "above_prior_range") return `Higher than every earlier result (${range}).`;
  return `Within your earlier results (${range}).`;
}

export function streakSentence(assessment: LabAssessment): string | null {
  if (assessment.outside_streak < 2) return null;
  return `Outside the lab's range on the last ${assessment.outside_streak} results.`;
}

export function gapSentence(gap: LabGap, unit: string): string {
  const days = Math.round(gap.days_apart);
  const apart = `${days} day${days === 1 ? "" : "s"} apart`;
  const diff =
    gap.difference == null
      ? "not compared (a limit or a different unit)"
      : `${labNumber(Math.abs(gap.difference))} ${unit} apart${
          gap.difference_pct != null ? ` (${signed(gap.difference_pct)}%)` : ""
        }`;
  return `${apart}, ${diff}.`;
}

export function latestResult(marker: Pick<LabMarker, "results">): LabResult | null {
  return marker.results.at(-1) ?? null;
}

// ── Chart geometry ────────────────────────────────────────────────
// x by time, y by value. Each result draws ITS OWN lab's band, spanning from
// the midpoint with its neighbours, so a change of lab (or of a lab's range)
// shows as a step, never as one blended band. Lines join results of the same
// lab only.

export type ChartPoint = { x: number; y: number; result: LabResult; series: number };
// A band edge is drawn only where the lab's bound is inside the plotted domain;
// a far bound is clipped at the chart edge (the band "continues beyond").
export type ChartBand = {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  series: number;
  topEdge: boolean;
  bottomEdge: boolean;
};
export type ChartLine = { d: string; series: number };
export type LabChartGeometry = {
  points: ChartPoint[];
  bands: ChartBand[];
  lines: ChartLine[];
  min: number;
  max: number;
};

export const CHART_W = 1000;
export const CHART_H = 100;
const PAD_X = 40;
const PAD_Y = 10;

export function labSeriesIndex(streamIds: string[], streamId: string): number {
  const at = streamIds.indexOf(streamId);
  return (at < 0 ? 0 : at) % 6;
}

export function labChartGeometry(results: LabResult[], streamOrder: string[]): LabChartGeometry | null {
  if (results.length === 0) return null;
  const sorted = [...results].sort((a, b) => Date.parse(a.specimen_at) - Date.parse(b.specimen_at));
  // Domain follows the values; a printed bound joins it only when it is near
  // them (within 1.5x the values' spread), so one wide range (ferritin 30-400)
  // cannot flatten the trace into the floor.
  const values = sorted.map((r) => r.value);
  const vMin = Math.min(...values);
  const vMax = Math.max(...values);
  const spread = Math.max(vMax - vMin, Math.abs(vMax) * 0.1, 1e-9);
  const near = (b: number | null): b is number =>
    b != null && Number.isFinite(b) && b >= vMin - 1.5 * spread && b <= vMax + 1.5 * spread;
  const bounds = sorted.flatMap((r) => [r.reference_low, r.reference_high]).filter(near);
  let min = Math.min(vMin, ...bounds);
  let max = Math.max(vMax, ...bounds);
  const pad = (max - min || Math.abs(max) || 1) * 0.12;
  min -= pad;
  max += pad;
  const clamp = (v: number) => Math.min(max, Math.max(min, v));
  const t0 = Date.parse(sorted[0].specimen_at);
  const t1 = Date.parse(sorted.at(-1)!.specimen_at);
  const span = t1 - t0;
  const x = (iso: string) =>
    span > 0 ? PAD_X + ((Date.parse(iso) - t0) / span) * (CHART_W - 2 * PAD_X) : CHART_W / 2;
  const y = (v: number) => PAD_Y + (CHART_H - 2 * PAD_Y) * (1 - (v - min) / (max - min));

  const points = sorted.map((result) => ({
    x: x(result.specimen_at),
    y: y(result.value),
    result,
    series: labSeriesIndex(streamOrder, result.stream_id),
  }));

  const bands: ChartBand[] = [];
  points.forEach((point, i) => {
    const { reference_low: low, reference_high: high } = point.result;
    if (low == null && high == null) return;
    const left = i === 0 ? 0 : (points[i - 1].x + point.x) / 2;
    const right = i === points.length - 1 ? CHART_W : (point.x + points[i + 1].x) / 2;
    bands.push({
      x0: left,
      x1: right,
      y0: y(clamp(high ?? max)),
      y1: y(clamp(low ?? min)),
      series: point.series,
      topEdge: high != null && high <= max,
      bottomEdge: low != null && low >= min,
    });
  });

  const lines: ChartLine[] = [];
  const byStream = new Map<string, ChartPoint[]>();
  for (const point of points) {
    const list = byStream.get(point.result.stream_id) ?? [];
    list.push(point);
    byStream.set(point.result.stream_id, list);
  }
  for (const list of byStream.values()) {
    if (list.length < 2) continue;
    lines.push({
      d: list.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" "),
      series: list[0].series,
    });
  }
  return { points, bands, lines, min, max };
}
