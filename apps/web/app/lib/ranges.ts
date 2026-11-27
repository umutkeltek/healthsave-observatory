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

// What a detail view can show for one requested range. Each case is its own
// state so a failed read can never pass for another range's data:
//   requested   - the requested range answered with usable readings
//   fallback    - the requested range answered with none; this is the ALL-TIME
//                 series, and it must be labelled as all time
//   empty       - nothing usable; olderData says whether all time was checked
//   unreachable - the requested range could not be read at all
export type RangeSeries =
  | { kind: "requested"; series: MetricSeries }
  | { kind: "fallback"; series: MetricSeries }
  | { kind: "empty"; olderData: "none" | "unknown" }
  | { kind: "unreachable" };

export type RangeSeriesView = {
  series: MetricSeries | null;
  /** The window the shown readings actually cover. */
  windowLabel: string;
  /** Disclosure to show above the chart, or null when the range speaks for itself. */
  note: string | null;
};

export function rangeSeriesView(read: RangeSeries, range: string): RangeSeriesView {
  const requested = rangeLabel(range);
  switch (read.kind) {
    case "requested":
      return { series: read.series, windowLabel: requested, note: null };
    case "fallback": {
      const coverage = seriesCoverage(read.series.points);
      const span = coverage ? ` (${shortDate(coverage.first)} → ${shortDate(coverage.last)})` : "";
      return {
        series: read.series,
        windowLabel: RANGE_LABELS.all,
        note: `No readings in the ${requested} range. Showing all ${coverage?.count ?? 0} available readings${span} instead.`,
      };
    }
    case "empty":
      return {
        series: null,
        windowLabel: requested,
        note:
          read.olderData === "unknown"
            ? `No readings in the ${requested} range. Older readings could not be checked right now.`
            : null,
      };
    case "unreachable":
      return {
        series: null,
        windowLabel: requested,
        note: `The Observatory API did not answer for the ${requested} range, so no readings can be shown right now.`,
      };
  }
}
