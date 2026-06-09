// Shared server-side loaders for the dashboard views. Each wraps a fetcher in a
// graceful null so a card can render its own "backend unreachable" state instead
// of crashing the page. Reused across the Overview and the per-view routes.

import {
  type Candidates,
  type ExperimentList,
  fetchCandidates,
  fetchExperiments,
  fetchFindings,
  fetchLatest,
  fetchMetrics,
  fetchPrivacy,
  fetchReadiness,
  fetchSeries,
  fetchSources,
  fetchStreams,
  isNarratorOff,
  type Finding,
  type InsightsLatest,
  type MetricSeries,
  type MetricSummary,
  type Privacy,
  type Readiness,
  type SourceView,
  type StreamView,
} from "./api";

// Curated sparkline metrics for the Data view grid. Each is a real ontology
// metric_id the v2 series endpoint serves; an empty one renders its own state.
export const GRID_METRICS: { id: string; title: string }[] = [
  { id: "vital.heart_rate", title: "Heart Rate" },
  { id: "vital.resting_heart_rate", title: "Resting Heart Rate" },
  { id: "vital.hrv_sdnn", title: "Heart Rate Variability" },
  { id: "vital.respiratory_rate", title: "Respiratory Rate" },
  { id: "activity.steps", title: "Steps" },
  { id: "activity.active_energy", title: "Active Energy" },
  { id: "body.weight", title: "Body Weight" },
];

export async function safeSeries(id: string, range = "7d"): Promise<MetricSeries | null> {
  try {
    return await fetchSeries(id, range);
  } catch {
    return null;
  }
}

export async function safeMetrics(): Promise<MetricSummary[] | null> {
  try {
    return await fetchMetrics();
  } catch {
    return null;
  }
}

export async function safeReadiness(): Promise<Readiness | null> {
  try {
    return await fetchReadiness();
  } catch {
    return null;
  }
}

export async function safeLatest(): Promise<InsightsLatest | null> {
  try {
    return await fetchLatest();
  } catch {
    return null;
  }
}

export async function safeFindings(): Promise<Finding[] | null> {
  try {
    return (await fetchFindings()).findings;
  } catch {
    return null;
  }
}

export async function safeCandidates(): Promise<Candidates | null> {
  try {
    return await fetchCandidates();
  } catch {
    return null;
  }
}

export async function safeExperiments(): Promise<ExperimentList | null> {
  try {
    return await fetchExperiments();
  } catch {
    return null;
  }
}

export async function safePrivacy(): Promise<Privacy | null> {
  try {
    return await fetchPrivacy();
  } catch {
    return null;
  }
}

// Identity / provenance loaders — the Sources view. Each returns the inner
// array (mirroring safeFindings) and degrades to null when the backend is
// unreachable so the page can fall back to a clearly-labelled demo.

export async function safeSources(): Promise<SourceView[] | null> {
  try {
    return (await fetchSources()).sources;
  } catch {
    return null;
  }
}

export async function safeStreams(): Promise<StreamView[] | null> {
  try {
    return (await fetchStreams()).streams;
  } catch {
    return null;
  }
}

export function loadGrid(): Promise<(MetricSeries | null)[]> {
  return Promise.all(GRID_METRICS.map((metric) => safeSeries(metric.id, "7d")));
}

// Recent values per readiness metric, for the inline row sparklines. Best-effort
// — a metric with no series just renders without one.
//
// Only the most-populated metrics get a sparkline: fetching a 30d series for
// EVERY metric is an N+1 storm that dominates home-page load at real scale
// (dozens of metrics x a series query each). The rest of the rows render
// gracefully without a sparkline.
const READINESS_SPARKLINE_LIMIT = 8;

export async function loadReadinessSparklines(
  readiness: Readiness | null,
): Promise<Record<string, number[]>> {
  if (!readiness) return {};
  const top = [...readiness.metrics]
    .sort((a, b) => (b.observation_count ?? 0) - (a.observation_count ?? 0))
    .slice(0, READINESS_SPARKLINE_LIMIT);
  const entries = await Promise.all(
    top.map(async (metric) => {
      const series = await safeSeries(metric.metric_id, "30d");
      const values = series
        ? series.points.map((p) => p.value).filter((v): v is number => v !== null)
        : [];
      return [metric.metric_id, values] as const;
    }),
  );
  return Object.fromEntries(entries);
}

// The shell's egress-posture chip, derived from the same privacy read the
// /privacy page uses. A narrator-off / no-egress host shows honestly as
// "on-host · no egress" instead of being bucketed as cloud; `ok=false` only
// when data *actually* leaves (a cloud provider with the opt-in active).
export type PostureChip = { text: string; ok: boolean };

export function postureChip(privacy: Privacy | null): PostureChip {
  // Backend unreachable: assert nothing we can't verify — just "on-host".
  if (!privacy) return { text: "on-host", ok: true };
  if (isNarratorOff(privacy.provider)) return { text: "on-host · no egress", ok: true };
  if (privacy.is_local) return { text: `local · ${privacy.provider}`, ok: true };
  if (privacy.cloud_active) return { text: `cloud · ${privacy.provider}`, ok: false };
  return { text: `cloud (off) · ${privacy.provider}`, ok: true };
}

// "2h ago" style relative label for the shell's sync status. Server-side only.
export function agoLabel(iso: string | null | undefined): string {
  if (!iso) return "never";
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}
