// Chart annotations: join persisted findings onto series points so charts can
// pin real, engine-detected events (not re-derived ones - the web never
// computes stats, it renders what the statistical engine persisted).
// Pure functions, unit-tested in annotations.test.ts.

import type { Finding } from "./api";

// The anomaly detector writes engine metric names ("heart_rate", "hrv"); the
// web charts key on ontology ids. Map the known engine names; a finding whose
// metric already looks like an ontology id (category.name) passes through.
const FINDING_METRIC_TO_ONTOLOGY: Record<string, string> = {
  heart_rate: "vital.heart_rate",
  hrv: "vital.hrv_sdnn",
  resting_heart_rate: "vital.resting_heart_rate",
  respiratory_rate: "vital.respiratory_rate",
};

export function findingMetricToOntology(metric: string | null): string | null {
  if (!metric) return null;
  if (metric.includes(".")) return metric;
  return FINDING_METRIC_TO_ONTOLOGY[metric] ?? null;
}

// Nearest-index join with a tolerance: an anomaly pins to the closest series
// point in time, but only if that point is within `toleranceMs` (default 36h -
// generous enough for daily buckets, tight enough that an anomaly from outside
// the charted range never pins to its edge).
const DEFAULT_TOLERANCE_MS = 36 * 3600_000;

export function anomalyPinIndices(
  pointTimes: string[],
  findings: Finding[] | null,
  metricId: string,
  toleranceMs = DEFAULT_TOLERANCE_MS,
): number[] {
  if (!findings || pointTimes.length === 0) return [];
  const times = pointTimes.map((t) => new Date(t).getTime());
  const pins = new Set<number>();
  for (const finding of findings) {
    if (finding.finding_type !== "anomaly") continue;
    if (findingMetricToOntology(finding.metric) !== metricId) continue;
    const detectedRaw = finding.structured_data?.detected_at;
    if (typeof detectedRaw !== "string") continue;
    const detected = new Date(detectedRaw).getTime();
    if (!Number.isFinite(detected)) continue;
    let nearest = -1;
    let best = Number.POSITIVE_INFINITY;
    for (let i = 0; i < times.length; i++) {
      const d = Math.abs(times[i] - detected);
      if (d < best) {
        best = d;
        nearest = i;
      }
    }
    if (nearest >= 0 && best <= toleranceMs) pins.add(nearest);
  }
  return [...pins].sort((a, b) => a - b);
}
