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
  stream_id: string | null;
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

// Server-side PUT — mirrors postJson. Used by the Intelligence settings apply.
async function putJson<T>(path: string, body: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
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

// A deployment with no LLM narrator (provider "disabled"/empty) performs zero
// egress — it is the *most* private posture, not "cloud". The egress classifier
// only knows ollama→local / everything-else→cloud, so a narrator-off host is
// bucketed as cloud; callers special-case it here so the UI never mislabels a
// no-egress host as a cloud one.
export function isNarratorOff(provider: string | null | undefined): boolean {
  const p = (provider ?? "").trim().toLowerCase();
  return p === "" || p === "disabled" || p === "none";
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

// Identity — Source / Device / Stream provenance (R2). Mirrors
// server/api/v2_identity.py. Streams join to sources on plugin_id; the
// dashboard renders this as the provenance / chain-of-origin surface.

export type SourceView = {
  id: string;
  plugin_id: string;
  display_name: string | null;
  first_seen_at: string;
  last_seen_at: string;
};

export type StreamView = {
  id: string;
  source_plugin_id: string;
  origin_key: string;
  device_label: string | null;
  first_seen_at: string;
  last_seen_at: string;
};

export type DeviceView = {
  device_label: string | null;
  stream_count: number;
  first_seen_at: string;
  last_seen_at: string;
};

export type SourcesResponse = { count: number; sources: SourceView[] };
export type StreamsResponse = { count: number; streams: StreamView[] };
export type DevicesResponse = { count: number; devices: DeviceView[] };

// Intelligence (LLM narrator) settings — the write surface. Mirrors
// server/api/v2_intelligence.py. Secrets are write-only: a key is sent in a
// request body and NEVER returned (the view carries only key_last4).

export type IntelMode = "off" | "local" | "cloud";

export type ConnectionView = {
  id: number;
  provider: string;
  display_name: string | null;
  base_url: string | null;
  destination: string; // "local" | "cloud"
  enabled: boolean;
  key_last4: string | null;
  last_test_status: string | null;
  last_test_at: string | null;
  model?: string | null; // present on the primary view
};

export type FallbackView = {
  priority: number;
  connection_id: number;
  provider: string | null;
  model: string;
  destination: string | null;
};

export type ConsentView = { granted: boolean; version: string | null; at: string | null };

export type IntelligenceView = {
  mode: IntelMode;
  managed_by_env: boolean;
  env_provider: string | null;
  allow_cloud_egress: boolean;
  redact_cloud_prompts: boolean;
  revision: number;
  consent: ConsentView;
  primary: ConnectionView | null;
  fallback: FallbackView[];
};

export type ConnectionInputPayload = {
  provider: string;
  model: string;
  base_url?: string | null;
  api_key?: string | null;
  display_name?: string | null;
};

export type PrimaryInputPayload = ConnectionInputPayload & {
  temperature?: number | null;
  max_tokens?: number | null;
};

export type ApplyIntelligencePayload = {
  mode: IntelMode;
  primary?: PrimaryInputPayload | null;
  fallback?: ConnectionInputPayload[] | null;
  redact_cloud_prompts?: boolean | null;
};

export type ConsentPayload = {
  granted: boolean;
  consent_version?: string | null;
  consent_text_hash?: string | null;
};

export type TestConnectionPayload = {
  connection_id?: number | null;
  provider?: string | null;
  model?: string | null;
  base_url?: string | null;
  api_key?: string | null;
};

export type TestConnectionResult = {
  ok: boolean;
  destination: string;
  model: string;
  latency_ms: number | null;
  error: string | null;
};

export type DetectCandidate = { url: string; reachable: boolean; models: string[] };
export type DetectLocalResult = { candidates: DetectCandidate[] };

export function fetchIntelligence(): Promise<IntelligenceView> {
  return getJson<IntelligenceView>("/api/v2/intelligence");
}

export function fetchDetectLocal(): Promise<DetectLocalResult> {
  return getJson<DetectLocalResult>("/api/v2/intelligence/detect-local");
}

export function applyIntelligence(body: ApplyIntelligencePayload): Promise<IntelligenceView> {
  return putJson<IntelligenceView>("/api/v2/intelligence", body);
}

export function postConsent(body: ConsentPayload): Promise<IntelligenceView> {
  return postJson<IntelligenceView>("/api/v2/intelligence/consent", body);
}

export function postTestConnection(body: TestConnectionPayload): Promise<TestConnectionResult> {
  return postJson<TestConnectionResult>("/api/v2/intelligence/test-connection", body);
}

export function fetchSources(): Promise<SourcesResponse> {
  return getJson<SourcesResponse>("/api/v2/sources");
}

export function fetchStreams(): Promise<StreamsResponse> {
  return getJson<StreamsResponse>("/api/v2/streams");
}

export function fetchDevices(): Promise<DevicesResponse> {
  return getJson<DevicesResponse>("/api/v2/devices");
}
