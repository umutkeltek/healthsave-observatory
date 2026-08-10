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
  ApiError,
  type AnalyticalTimeSettings,
  type Candidates,
  type Correlation,
  type ExperimentList,
  type ExportMetricInfo,
  fetchAnalyticalTime,
  fetchCandidates,
  fetchCorrelations,
  fetchExperiments,
  fetchExportMetrics,
  fetchFindings,
  fetchIntelligence,
  fetchLatest,
  fetchMetrics,
  fetchMoments,
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
  type Moment,
  type NarrativeHistoryItem,
  type Privacy,
  type Readiness,
  type Receipts,
  type SourceView,
  type StreamView,
} from "./api";
import { formatAgo } from "./format";
import { hasUsablePoints } from "./ranges";
import { swrCache } from "./ttlCache";

// The one logged choke point for swallowed fetch failures: a card rendering
// its empty state is fine UX, but the operator debugging "dashboard shows
// nothing" needs the 401-vs-timeout-vs-refused distinction in the server log.
// Deduped per label+message so a hot page doesn't spam.
const _warned = new Set<string>();
function swallow(label: string, error: unknown): null {
  const message = error instanceof Error ? error.message : String(error);
  const key = `${label}:${message}`;
  if (!_warned.has(key)) {
    _warned.add(key);
    console.warn(`[load] ${label} degraded to null: ${message}`);
  }
  return null;
}

// Curated sparkline metrics for the Data view grid. Each is a real ontology
// metric_id the v2 series endpoint serves; an empty one renders its own state.
// Default Today grid: the cardiovascular core + the activity/mobility surface
// the iOS device actually has. Walking metrics were added when full-export
// support landed — they're sparse but real, so the UI must surface them so
// users see they exist and have data, not bury them.
export const GRID_METRICS: { id: string; title: string }[] = [
  { id: "vital.heart_rate", title: "Heart Rate" },
  { id: "vital.resting_heart_rate", title: "Resting Heart Rate" },
  { id: "vital.walking_heart_rate_average", title: "Walking Heart Rate" },
  { id: "vital.hrv_sdnn", title: "Heart Rate Variability" },
  { id: "vital.respiratory_rate", title: "Respiratory Rate" },
  { id: "mobility.walking_speed", title: "Walking Speed" },
  { id: "mobility.walking_step_length", title: "Step Length" },
  { id: "activity.steps", title: "Steps" },
  { id: "activity.exercise_minutes", title: "Exercise Minutes" },
  { id: "activity.active_energy", title: "Active Energy" },
  { id: "body.weight", title: "Body Weight" },
];

export async function safeAnalyticalTime(): Promise<AnalyticalTimeSettings | null> {
  try {
    return await swrCache("analytical-time", 30_000, fetchAnalyticalTime);
  } catch (error) {
    return swallow("analytical-time", error);
  }
}

export async function safeSeries(id: string, range = "7d"): Promise<MetricSeries | null> {
  try {
    return await swrCache(`series:${id}:${range}`, 30_000, () => fetchSeries(id, range));
  } catch (error) {
    return swallow("loader", error);
  }
}

// One request for many metrics, keyed by metric id. Falls back to the
// per-metric endpoint when /api/v2/series is unavailable (older backend), so
// a newer web can deploy ahead of the API without blanking the grid. The
// cache key is the joined id string - call through safeSeriesMany.
const batchSeriesCached = cache(
  async (idsKey: string, range: string): Promise<Map<string, MetricSeries>> => {
    const ids = idsKey.split("\u0000");
    const map = new Map<string, MetricSeries>();
    try {
      const batch = await swrCache(`series-batch:${idsKey}:${range}`, 30_000, () =>
        fetchSeriesBatch(ids, range),
      );
      for (const item of batch.series) {
        if (item.metric && item.points) {
          map.set(item.metric.id, {
            metric: item.metric,
            range: batch.range,
            start: batch.start,
            end: batch.end,
            points: item.points,
          });
        } else if (item.error) {
          // A typo'd pinned/grid id should be visible, not a forever-empty card.
          swallow("series-batch-item", new Error(`${item.metric_id}: ${item.error}`));
        }
      }
      return map;
    } catch (error) {
      // Documented fallback for an older backend without /api/v2/series (404)
      // - but a 500/timeout/auth failure lands here too, so log before
      // fanning out or a batch-endpoint regression stays invisible.
      swallow("series-batch", error);
      const series = await Promise.all(ids.map((id) => safeSeries(id, range)));
      for (const s of series) if (s) map.set(s.metric.id, s);
      return map;
    }
  },
);

export function safeSeriesMany(ids: string[], range = "7d"): Promise<Map<string, MetricSeries>> {
  // NUL separator: ids are cookie-influenced strings, so a comma join could
  // collide ("a,b"+"c" vs "a"+"b,c"); NUL can't appear in a metric id.
  return batchSeriesCached(ids.join("\u0000"), range);
}

// The static registry catalog, the two heavy coverage reads, and the series
// batch/per-metric reads ride the process-level SWR cache: first request
// after boot pays the real cost, every later page view is served instantly
// and refreshed in the background.
export const safeMetrics = cache(async (): Promise<MetricSummary[] | null> => {
  try {
    return await swrCache("metrics-catalog", 300_000, fetchMetrics);
  } catch (error) {
    return swallow("loader", error);
  }
});

export const safeReadiness = cache(async (): Promise<Readiness | null> => {
  try {
    return await swrCache("readiness", 30_000, fetchReadiness);
  } catch (error) {
    return swallow("loader", error);
  }
});

export const safeLatest = cache(async (): Promise<InsightsLatest | null> => {
  try {
    return await fetchLatest();
  } catch (error) {
    return swallow("loader", error);
  }
});

export const safeFindings = cache(async (): Promise<Finding[] | null> => {
  try {
    return (await fetchFindings()).findings;
  } catch (error) {
    return swallow("loader", error);
  }
});

export const safeExportMetrics = cache(async (): Promise<ExportMetricInfo[] | null> => {
  try {
    // Counts one full-table aggregate per exportable metric - ride the SWR
    // cache like the other heavy coverage reads.
    return await swrCache("export-metrics", 60_000, fetchExportMetrics);
  } catch (error) {
    return swallow("loader", error);
  }
});

export const safeCorrelations = cache(async (): Promise<Correlation[] | null> => {
  try {
    return (await fetchCorrelations()).correlations;
  } catch (error) {
    return swallow("loader", error);
  }
});

export async function safeCandidates(): Promise<Candidates | null> {
  try {
    return await fetchCandidates();
  } catch (error) {
    return swallow("loader", error);
  }
}

export async function safeExperiments(): Promise<ExperimentList | null> {
  try {
    return await fetchExperiments();
  } catch (error) {
    return swallow("loader", error);
  }
}

export const safePrivacy = cache(async (): Promise<Privacy | null> => {
  try {
    return await fetchPrivacy();
  } catch (error) {
    return swallow("loader", error);
  }
});

export const safeReceipts = cache(async (): Promise<Receipts | null> => {
  try {
    return await swrCache("receipts", 60_000, () => fetchReceipts());
  } catch (error) {
    return swallow("loader", error);
  }
});

export const safeNarratives = cache(async (): Promise<NarrativeHistoryItem[] | null> => {
  try {
    return (await fetchNarratives()).narratives;
  } catch (error) {
    return swallow("loader", error);
  }
});

export async function safeIntelligence(): Promise<IntelligenceView | null> {
  try {
    return await fetchIntelligence();
  } catch (error) {
    return swallow("loader", error);
  }
}

// Shared "is there anything to show?" verdict for the Today page's streamed
// sections. Every input is cache()'d, so each section can ask independently
// at the cost of one upstream read per surface per request.
//
// Three-way on purpose: "empty" (backend answered, no data yet - keep
// syncing) and "unreachable" (every read failed - wrong API_BASE/API_KEY or
// backend down) demand DIFFERENT user actions; collapsing them made the hero
// tell a misconfigured user to sync forever. The loaders only return null on
// a thrown fetch, so all-null ⇒ unreachable.
export type DataState = "data" | "empty" | "unreachable";

export async function dataState(): Promise<DataState> {
  const [readiness, latest, findings] = await Promise.all([
    safeReadiness(),
    safeLatest(),
    safeFindings(),
  ]);
  const hasData =
    (readiness?.metrics.length ?? 0) > 0 ||
    Boolean(latest?.daily_briefing) ||
    (findings?.length ?? 0) > 0;
  if (hasData) return "data";
  if (readiness === null && latest === null && findings === null) return "unreachable";
  return "empty";
}

export async function hasAnyData(): Promise<boolean> {
  return (await dataState()) === "data";
}

// ── Range-fallback loader ────────────────────────────────────────────────
// When the requested period holds no usable observations, re-fetch with the
// widest available window so the UI can show the oldest data it actually has.
// The caller receives `{ requested, fallback }`; it should render the
// fallback data with an explicit disclosure, never relabel old data as
// belonging to the requested period.
export async function safeSeriesWithFallback(
  id: string,
  range: string,
): Promise<{ requested: MetricSeries | null; fallback: MetricSeries | null }> {
  if (range === "all") {
    const series = await safeSeries(id, "all");
    return { requested: series, fallback: null };
  }
  const requested = await safeSeries(id, range);
  if (hasUsablePoints(requested)) return { requested, fallback: null };
  const fallback = await safeSeries(id, "all");
  return { requested, fallback: hasUsablePoints(fallback) ? fallback : null };
}

// Identity / provenance loaders - the Sources view. Each returns the inner
// array (mirroring safeFindings) and degrades to null when the backend is
// unreachable so the page can fall back to a clearly-labelled demo.

export async function safeMoments(limit = 50): Promise<Moment[]> {
  try {
    const result = await swrCache("moments", 30_000, () => fetchMoments(limit));
    return result.moments;
  } catch (error) {
    return swallow("moments", error) ?? [];
  }
}

export async function safeSources(): Promise<SourceView[] | null> {
  try {
    return (await fetchSources()).sources;
  } catch (error) {
    return swallow("loader", error);
  }
}

export async function safeStreams(): Promise<StreamView[] | null> {
  try {
    return (await fetchStreams()).streams;
  } catch (error) {
    return swallow("loader", error);
  }
}

// Recent values per readiness metric, for the inline row sparklines. Best-effort
// - a metric with no series just renders without one.
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
  // Backend unreachable: assert nothing we can't verify - just "on-host".
  if (!privacy) return { text: "on-host", ok: true };
  if (isNarratorOff(privacy.provider)) return { text: "on-host · no egress", ok: true };
  if (privacy.is_local) return { text: `local · ${privacy.provider}`, ok: true };
  if (privacy.cloud_active) return { text: `cloud · ${privacy.provider}`, ok: false };
  return { text: `cloud (off) · ${privacy.provider}`, ok: true };
}

// "2h ago" style relative label for the shell's sync status. Server-side only.
// Delegates to the shared formatter so there's one definition of relative time.
export function agoLabel(iso: string | null | undefined): string {
  return formatAgo(iso);
}
