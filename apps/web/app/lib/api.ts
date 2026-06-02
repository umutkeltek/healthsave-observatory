// Typed client for the datahub v2 read API (the same contract the LLM narrator
// consumes). Shapes mirror server/api/v2_metrics.py responses.

export type MetricSummary = {
  id: string;
  display_name: string;
  category: string;
  value_type: string;
  canonical_unit: string | null;
};

export type SeriesPoint = {
  t: string;
  value: number | null;
  code: string | null;
  unit: string | null;
  source_id: string;
  confidence: number | null;
};

export type MetricSeries = {
  metric: MetricSummary;
  range: string;
  start: string;
  end: string;
  points: SeriesPoint[];
};

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";
// Server-side only — the key stays in the Next server (these are server
// components), never shipped to the browser.
const API_KEY = process.env.API_KEY ?? "";

async function getJson<T>(path: string): Promise<T> {
  const headers: Record<string, string> = {};
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export function fetchMetrics(): Promise<MetricSummary[]> {
  return getJson<MetricSummary[]>("/api/v2/metrics");
}

export function fetchSeries(metricId: string, range = "7d"): Promise<MetricSeries> {
  return getJson<MetricSeries>(`/api/v2/metrics/${metricId}/series?range=${range}`);
}

// Data-readiness — Insight Action Loop card #1. Mirrors server/api/v2_readiness.py.

export type GateVerdict = {
  is_sufficient: boolean;
  missing: string | null;
  days_until_sufficient: number | null;
};

export type MetricReadiness = {
  metric_id: string;
  display_name: string;
  category: string | null;
  observation_count: number;
  days_with_data: number;
  first_observation_at: string | null;
  last_observation_at: string | null;
  // Keyed by analysis type (anomaly_detection, trend_analysis).
  analyzable: Record<string, GateVerdict>;
};

export type SourceReadiness = {
  source_plugin_id: string | null;
  observation_count: number;
  last_ingested_at: string | null;
};

export type Readiness = {
  as_of: string;
  last_observation_at: string | null;
  last_ingested_at: string | null;
  sources: SourceReadiness[];
  metrics: MetricReadiness[];
  summary: { metrics_with_data: number };
};

export function fetchReadiness(): Promise<Readiness> {
  return getJson<Readiness>("/api/v2/readiness");
}
