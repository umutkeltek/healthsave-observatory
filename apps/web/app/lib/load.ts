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
  fetchPrivacy,
  fetchReadiness,
  fetchSeries,
  type Finding,
  type InsightsLatest,
  type MetricSeries,
  type Privacy,
  type Readiness,
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

export function loadGrid(): Promise<(MetricSeries | null)[]> {
  return Promise.all(GRID_METRICS.map((metric) => safeSeries(metric.id, "7d")));
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
