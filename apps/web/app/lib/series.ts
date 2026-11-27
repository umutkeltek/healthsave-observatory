import type { SeriesPoint } from "./api";

export type NumericSeriesSummary = {
  latest: (SeriesPoint & { value: number }) | null;
  average: number | null;
};

const OWNER_DAILY_TOTAL_SCOPE = "owner_all_source_day_total";

export function hasOwnerDailyTotalSemantics(points: SeriesPoint[]): boolean {
  return points.some((point) => point.aggregation_scope === OWNER_DAILY_TOTAL_SCOPE);
}

// Series endpoints currently return ascending timestamps, but UI correctness
// should not depend on transport order. Resolve the latest valued observation
// explicitly and compute the average over every finite numeric reading.
export function summarizeNumericSeries(points: SeriesPoint[]): NumericSeriesSummary {
  const valued = points.filter(
    (point): point is SeriesPoint & { value: number } =>
      point.value !== null && Number.isFinite(point.value) && Number.isFinite(Date.parse(point.t)),
  );
  if (valued.length === 0) return { latest: null, average: null };

  const latest = valued.reduce((current, point) =>
    Date.parse(point.t) > Date.parse(current.t) ? point : current,
  );
  const average = valued.reduce((sum, point) => sum + point.value, 0) / valued.length;
  return { latest, average };
}

// One group per device stream, newest reading first. A metric that two devices
// report (an Apple Watch and a Whoop) is shown as two readings, never one
// averaged line (healthOpinion.ts). All-source day totals stay one group.
export type SourceGroup = {
  key: string;
  sourceId: string;
  streamId: string | null;
  points: (SeriesPoint & { value: number })[];
  latest: SeriesPoint & { value: number };
};

export function splitBySource(points: SeriesPoint[]): SourceGroup[] {
  const groups = new Map<string, SourceGroup>();
  for (const point of points) {
    if (point.value === null || !Number.isFinite(point.value) || !Number.isFinite(Date.parse(point.t))) continue;
    const valued = point as SeriesPoint & { value: number };
    const key = `${point.source_id}|${point.stream_id ?? ""}`;
    const group = groups.get(key);
    if (group) {
      group.points.push(valued);
      if (Date.parse(valued.t) >= Date.parse(group.latest.t)) group.latest = valued;
    } else {
      groups.set(key, { key, sourceId: point.source_id, streamId: point.stream_id ?? null, points: [valued], latest: valued });
    }
  }
  for (const group of groups.values()) group.points.sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
  return [...groups.values()].sort((a, b) => Date.parse(b.latest.t) - Date.parse(a.latest.t) || a.key.localeCompare(b.key));
}

// A device name for one group: the stream's own label, then the caller's
// fallback, never a bare id.
export function sourceGroupLabel(group: SourceGroup, labels: Record<string, string>, index: number): string {
  return (group.streamId && labels[group.streamId]) || labels[group.sourceId] || `Source ${index + 1}`;
}
