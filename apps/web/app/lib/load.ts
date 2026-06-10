// Shared server-side loaders for the dashboard views. Each wraps a fetcher in a
// graceful null so a card can render its own "backend unreachable" state instead
// of crashing the page. Reused across the Overview and the per-view routes.
//
// The hot read paths are wrapped in React cache(): the layout chrome and
// several Suspense-streamed sections read the same surfaces (readiness,
// privacy, latest, findings) in one render pass, and cache() collapses those
// to a single upstream fetch per request.

import { cache } from "react";

import {
  type Candidates,
  type ExperimentList,
  fetchCandidates,
  fetchExperiments,
  fetchFindings,
  fetchIntelligence,
  fetchLatest,
  fetchMetrics,
  fetchNarratives,
  fetchPrivacy,
  fetchReadiness,
  fetchReceipts,
  fetchSeries,
  fetchSeriesBatch,
  fetchSources,
  fetchStreams,
  isNarratorOff,
  type Finding,
  type IntelligenceView,
  type InsightsLatest,
  type MetricSeries,
  type MetricSummary,
  type NarrativeHistoryItem,
  type Privacy,
  type Readiness,
  type Receipts,
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

// One request for many metrics, keyed by metric id. Falls back to the
// per-metric endpoint when /api/v2/series is unavailable (older backend), so
// a newer web can deploy ahead of the API without blanking the grid. The
// cache key is the joined id string — call through safeSeriesMany.
const batchSeriesCached = cache(
  async (idsKey: string, range: string): Promise<Map<string, MetricSeries>> => {
    const ids = idsKey.split(",");
    const map = new Map<string, MetricSeries>();
    try {
      const batch = await fetchSeriesBatch(ids, range);
      for (const item of batch.series) {
        if (item.metric && item.points) {
          map.set(item.metric.id, {
            metric: item.metric,
            range: batch.range,
            start: batch.start,
            end: batch.end,
            points: item.points,
          });
        }
      }
      return map;
    } catch {
      const series = await Promise.all(ids.map((id) => safeSeries(id, range)));
      for (const s of series) if (s) map.set(s.metric.id, s);
      return map;
    }
  },
);

export function safeSeriesMany(ids: string[], range = "7d"): Promise<Map<string, MetricSeries>> {
  return batchSeriesCached(ids.join(","), range);
}

export const safeMetrics = cache(async (): Promise<MetricSummary[] | null> => {
  try {
    return await fetchMetrics();
  } catch {
    return null;
  }
});

export const safeReadiness = cache(async (): Promise<Readiness | null> => {
  try {
    return await fetchReadiness();
  } catch {
    return null;
  }
});

export const safeLatest = cache(async (): Promise<InsightsLatest | null> => {
  try {
    return await fetchLatest();
  } catch {
    return null;
  }
});

export const safeFindings = cache(async (): Promise<Finding[] | null> => {
  try {
    return (await fetchFindings()).findings;
  } catch {
    return null;
  }
});

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

export const safePrivacy = cache(async (): Promise<Privacy | null> => {
  try {
    return await fetchPrivacy();
  } catch {
    return null;
  }
});

export const safeReceipts = cache(async (): Promise<Receipts | null> => {
  try {
    return await fetchReceipts();
  } catch {
    return null;
  }
});

export const safeNarratives = cache(async (): Promise<NarrativeHistoryItem[] | null> => {
  try {
    return (await fetchNarratives()).narratives;
  } catch {
    return null;
  }
});

export async function safeIntelligence(): Promise<IntelligenceView | null> {
  try {
    return await fetchIntelligence();
  } catch {
    return null;
  }
}

// Shared "is there anything to show?" verdict for the Today page's streamed
// sections. Every input is cache()'d, so each section can ask independently
// at the cost of one upstream read per surface per request.
export async function hasAnyData(): Promise<boolean> {
  const [readiness, latest, findings] = await Promise.all([
    safeReadiness(),
    safeLatest(),
    safeFindings(),
  ]);
  return (
    (readiness?.metrics.length ?? 0) > 0 ||
    Boolean(latest?.daily_briefing) ||
    (findings?.length ?? 0) > 0
  );
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

export async function loadGrid(): Promise<(MetricSeries | null)[]> {
  const map = await safeSeriesMany(
    GRID_METRICS.map((metric) => metric.id),
    "7d",
  );
  return GRID_METRICS.map((metric) => map.get(metric.id) ?? null);
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
  const map = await safeSeriesMany(
    top.map((metric) => metric.metric_id),
    "30d",
  );
  const entries = top.map((metric) => {
    const series = map.get(metric.metric_id);
    const values = series
      ? series.points.map((p) => p.value).filter((v): v is number => v !== null)
      : [];
    return [metric.metric_id, values] as const;
  });
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
