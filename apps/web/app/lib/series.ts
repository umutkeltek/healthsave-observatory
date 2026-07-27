import type { SeriesPoint } from "./api";

export type NumericSeriesSummary = {
  latest: (SeriesPoint & { value: number }) | null;
  average: number | null;
};

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
