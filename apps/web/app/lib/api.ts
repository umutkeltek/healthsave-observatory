// Typed client for the HealthSave Observatory v2 read API (the same contract the LLM narrator
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

// Server-side POST — used by the experiment write actions. The key never
// reaches the browser (these run in server actions). On error we surface the
// backend's `detail` (e.g. a 422 readiness rationale) so the UI can show it.
async function postJson<T>(path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    cache: "no-store",
    headers,
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    let detail = `${path} -> ${res.status}`;
    try {
      const payload = (await res.json()) as { detail?: unknown };
      if (payload?.detail) {
        detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail);
      }
    } catch {
      // non-JSON error body — keep the status line
    }
    throw new Error(detail);
  }
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

// Insights — Weekly Brief (narratives) + Evidence (findings).
// Mirrors server/api/v2_insights.py /latest + /findings.

export type Narrative = {
  insight_type: string;
  narrative: string;
  created_at: string | null;
};

export type InsightsLatest = {
  daily_briefing: Narrative | null;
  weekly_summary: Narrative | null;
};

export type Finding = {
  id: number;
  finding_type: string | null;
  metric: string | null;
  severity: string | null;
  structured_data: Record<string, unknown>;
  created_at: string | null;
};

export type FindingsList = {
  findings: Finding[];
  count: number;
};

export function fetchLatest(): Promise<InsightsLatest> {
  return getJson<InsightsLatest>("/api/v2/insights/latest");
}

export function fetchFindings(type?: string): Promise<FindingsList> {
  const query = type ? `?type=${encodeURIComponent(type)}` : "";
  return getJson<FindingsList>(`/api/v2/insights/findings${query}`);
}

// Experiment candidates — "what to try next". Mirrors
// server/api/v2_experiments.py /candidates.

export type ExperimentReadiness = {
  verdict: string; // "testable" | "not_controllable"
  lever: string | null;
  outcome: string | null;
  suggested_protocol: string | null;
  required_days: number | null;
  rationale: string;
};

export type Candidate = {
  metric_a: string;
  metric_b: string;
  coefficient: number | null;
  method: string | null;
  period_days: number | null;
  p_value: number | null;
  created_at: string | null;
  readiness: ExperimentReadiness;
};

export type Candidates = {
  candidates: Candidate[];
  count: number;
  testable_count: number;
};

export function fetchCandidates(): Promise<Candidates> {
  return getJson<Candidates>("/api/v2/experiments/candidates");
}

// Egress posture — "what leaves this host". Mirrors server/api/v2_privacy.py.

export type EgressClass = {
  payload_class: string;
  allowed: boolean;
  leaves_host: boolean;
  reason: string;
};

export type Privacy = {
  provider: string;
  destination: string; // "local" | "cloud"
  is_local: boolean;
  allow_cloud_egress: boolean;
  cloud_active: boolean;
  raw_observations_leave_host: boolean;
  egress: EgressClass[];
};

export function fetchPrivacy(): Promise<Privacy> {
  return getJson<Privacy>("/api/v2/privacy");
}

// Experiments — committed n-of-1 ABAB runs. Mirrors the lifecycle routes in
// server/api/v2_experiments.py (ExperimentView et al.).

export type Phase = {
  label: string; // "A" (baseline) | "B" (intervention)
  index: number;
  start: string;
  end: string;
};

export type Progress = {
  current_phase: string | null;
  day_index: number;
  total_days: number;
  days_remaining: number;
  is_complete: boolean;
  pct: number;
};

export type ExperimentResult = {
  kind: string; // "retrospective" | "controlled"
  computed_at: string;
  direction: string | null;
  diff: number | null;
  effect_size: number | null;
  p_value: number | null;
  inference: string | null;
  summary: string | null;
  n_a: number | null;
  n_b: number | null;
  mean_a: number | null;
  mean_b: number | null;
  n_blocks_used: number | null;
  caveat: string | null;
  adherence: Record<string, unknown> | null;
};

export type Experiment = {
  id: string;
  lever_metric_id: string;
  outcome_metric_id: string;
  lever: string; // human-readable tail
  outcome: string;
  design: string;
  block_days: number;
  start_date: string;
  hypothesis: string | null;
  status: string; // "collecting" | "completed" | "abandoned"
  created_at: string;
  calendar: Phase[];
  progress: Progress;
  results: Record<string, ExperimentResult>;
};

export type ExperimentList = {
  experiments: Experiment[];
  count: number;
};

export function fetchExperiments(status?: string): Promise<ExperimentList> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return getJson<ExperimentList>(`/api/v2/experiments${query}`);
}

export function fetchExperiment(id: string): Promise<Experiment> {
  return getJson<Experiment>(`/api/v2/experiments/${id}`);
}

// Write helpers — server-side only, called from server actions (lib/actions.ts).

export function createExperiment(body: {
  lever_metric_id: string;
  outcome_metric_id: string;
  design?: string;
  block_days?: number;
  start_date?: string;
  hypothesis?: string | null;
}): Promise<Experiment> {
  return postJson<Experiment>("/api/v2/experiments", body);
}

export function analyzeExperiment(id: string): Promise<Experiment> {
  return postJson<Experiment>(`/api/v2/experiments/${id}/analyze`, {});
}

export function abandonExperiment(id: string): Promise<Experiment> {
  return postJson<Experiment>(`/api/v2/experiments/${id}/abandon`, {});
}
