// Pure config for the Explore surface — the composable dashboard. State lives in
// the URL (shareable, server-rendered, mirrors FilterBar/CompareControls), never
// in a client store. A dashboard is a global {range, grain, stat} plus a list of
// panels; each panel is a chart kind over one-or-more metrics. No I/O here.

import type { Grain, Stat } from "./analytics";

export type ChartKind = "line" | "heatmap" | "weekday" | "zones";
export type GrainOpt = Grain | "raw";

export type ExplorePanel = { chart: ChartKind; metrics: string[] };
export type ExploreState = {
  range: string;
  grain: GrainOpt;
  stat: Stat;
  // Optional custom window (YYYY-MM-DD). When set, it overrides `range`: the page
  // fetches the widest preset and slices points to [from, to] client-side, so no
  // backend change is needed.
  from?: string;
  to?: string;
  panels: ExplorePanel[];
};

// Range presets. "all" hits the backend with the widest possible window so the
// page is never hiding data the user actually has — the earlier presets mask
// sparse back-histories from the iOS device's full-export cadence.
export const EXPLORE_RANGES = ["24h", "7d", "30d", "90d", "1y", "all"] as const;
export const EXPLORE_RANGE_LABELS: Record<(typeof EXPLORE_RANGES)[number], string> = {
  "24h": "24 hours",
  "7d": "7 days",
  "30d": "30 days",
  "90d": "90 days",
  "1y": "1 year",
  "all": "All time",
};
export const EXPLORE_GRAINS: { id: GrainOpt; label: string }[] = [
  { id: "raw", label: "Raw" },
  { id: "hour", label: "Hourly" },
  { id: "day", label: "Daily" },
  { id: "week", label: "Weekly" },
];
export const EXPLORE_STATS: { id: Stat; label: string }[] = [
  { id: "mean", label: "Average" },
  { id: "max", label: "Max" },
  { id: "min", label: "Min" },
  { id: "sum", label: "Sum" },
];
export const CHART_KINDS: { id: ChartKind; label: string }[] = [
  { id: "line", label: "Line" },
  { id: "heatmap", label: "Week × hour" },
  { id: "weekday", label: "By weekday" },
  { id: "zones", label: "HR zones" },
];

// Default Explore dashboard covers the five richest dimensions in the catalog:
// autonomic recovery (HRV, RHR), walking load (walking HR + step length +
// asymmetry in one overlay), activity (steps + exercise minutes), and a weekday
// pivot over HRV so "when in the week I'm actually recovered" is one glance.
// Curated, not random — every panel answers a question a returning user asks.
const DEFAULT_PANELS: ExplorePanel[] = [
  { chart: "line", metrics: ["vital.hrv_sdnn"] },
  { chart: "line", metrics: ["vital.resting_heart_rate"] },
  { chart: "line", metrics: ["vital.walking_heart_rate_average", "mobility.walking_step_length", "mobility.walking_asymmetry"] },
  { chart: "line", metrics: ["activity.steps", "activity.exercise_minutes"] },
  { chart: "weekday", metrics: ["vital.hrv_sdnn"] },
];

const isGrain = (v: string): v is GrainOpt => EXPLORE_GRAINS.some((g) => g.id === v);
const isStat = (v: string): v is Stat => EXPLORE_STATS.some((s) => s.id === v);
const isChart = (v: string): v is ChartKind => CHART_KINDS.some((c) => c.id === v);

// Panels encode as `<chart>:<metric>,<metric>` segments joined by ';'. Metric ids
// contain '.' and '_' but never ':', ',' or ';', so this round-trips cleanly.
export function encodePanels(panels: ExplorePanel[]): string {
  return panels.map((p) => `${p.chart}:${p.metrics.join(",")}`).join(";");
}

export function parsePanels(raw: string | undefined): ExplorePanel[] {
  if (!raw) return DEFAULT_PANELS;
  const panels = raw
    .split(";")
    .map((seg) => {
      const [chart, metrics] = seg.split(":");
      const ms = (metrics ?? "").split(",").filter(Boolean);
      return { chart: isChart(chart) ? chart : "line", metrics: ms } as ExplorePanel;
    })
    .filter((p) => p.metrics.length > 0);
  return panels.length ? panels : DEFAULT_PANELS;
}

const isDate = (v: string | undefined): v is string => !!v && /^\d{4}-\d{2}-\d{2}$/.test(v);

export function parseExploreState(sp: {
  range?: string;
  grain?: string;
  stat?: string;
  from?: string;
  to?: string;
  panels?: string;
}): ExploreState {
  const state: ExploreState = {
    range: (EXPLORE_RANGES as readonly string[]).includes(sp.range ?? "") ? sp.range! : "30d",
    grain: sp.grain && isGrain(sp.grain) ? sp.grain : "day",
    stat: sp.stat && isStat(sp.stat) ? sp.stat : "mean",
    panels: parsePanels(sp.panels),
  };
  if (isDate(sp.from)) state.from = sp.from;
  if (isDate(sp.to)) state.to = sp.to;
  return state;
}

// Serialize a full state back to a query string (used by the client controls to
// mutate the URL and by "copy view" links).
export function encodeExploreState(state: ExploreState): string {
  const qs = new URLSearchParams();
  qs.set("range", state.range);
  qs.set("grain", state.grain);
  qs.set("stat", state.stat);
  if (state.from) qs.set("from", state.from);
  if (state.to) qs.set("to", state.to);
  qs.set("panels", encodePanels(state.panels));
  return qs.toString();
}

// The preset to actually fetch: a custom window pulls the widest preset (the page
// then slices it), otherwise the chosen preset. "all" is its own widest preset.
export function fetchRange(state: ExploreState): string {
  if (state.range === "all") return "all";
  return state.from || state.to ? "1y" : state.range;
}

// Slice points to a custom [from, to] window (inclusive). ISO timestamps compare
// lexicographically, so string bounds are correct.
export function filterWindow<T extends { t: string }>(points: T[], from?: string, to?: string): T[] {
  if (!from && !to) return points;
  const lo = from ?? "";
  const hi = to ? `${to}T23:59:59.999Z` : "￿";
  return points.filter((p) => p.t >= lo && p.t <= hi);
}

// Min-max normalize a series to 0..1 so metrics with different units can share
// one axis honestly (each on its own scale — never a merged value). A flat series
// maps to 0.5.
export function normalize(values: number[]): number[] {
  if (values.length === 0) return values;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  if (span === 0) return values.map(() => 0.5);
  return values.map((v) => (v - min) / span);
}
