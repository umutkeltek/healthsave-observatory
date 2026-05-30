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

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export function fetchMetrics(): Promise<MetricSummary[]> {
  return getJson<MetricSummary[]>("/api/v2/metrics");
}

export function fetchSeries(metricId: string, range = "7d"): Promise<MetricSeries> {
  return getJson<MetricSeries>(`/api/v2/metrics/${metricId}/series?range=${range}`);
}
