import type { MetricSeries, SeriesPoint } from "./api";

export const RANGE_OPTIONS = ["24h", "7d", "30d", "90d", "1y", "all"] as const;
export type RangeOption = (typeof RANGE_OPTIONS)[number];

export const RANGE_LABELS: Record<RangeOption, string> = {
  "24h": "24 hours",
  "7d": "7 days",
  "30d": "30 days",
  "90d": "90 days",
  "1y": "1 year",
  all: "All time",
};

export function isRangeOption(value: string | undefined): value is RangeOption {
  return RANGE_OPTIONS.includes(value as RangeOption);
}

export function rangeLabel(range: string): string {
  return isRangeOption(range) ? RANGE_LABELS[range] : range;
}

export function hasUsablePoints(series: MetricSeries | null): series is MetricSeries {
  return Boolean(
    series?.points.some(
      (point) =>
        Number.isFinite(Date.parse(point.t)) &&
        ((point.value !== null && Number.isFinite(point.value)) || point.code !== null),
    ),
  );
}

export type SeriesCoverage = {
  first: string;
  last: string;
  count: number;
};

export function seriesCoverage(points: SeriesPoint[]): SeriesCoverage | null {
  const valid = points
    .filter((point) => Number.isFinite(Date.parse(point.t)) && (point.value !== null || point.code !== null))
    .slice()
    .sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
  if (valid.length === 0) return null;
  return { first: valid[0].t, last: valid[valid.length - 1].t, count: valid.length };
}

export function shortDate(iso: string): string {
  const date = new Date(iso);
  return Number.isFinite(date.getTime())
    ? date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
    : iso;
}
