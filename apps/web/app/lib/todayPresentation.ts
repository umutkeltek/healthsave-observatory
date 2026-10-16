import type { Finding, MetricSeries, SeriesPoint } from "./api";
import { groupFindingsForDisplay } from "./findingPresentation";
import { hasOwnerDailyTotalSemantics } from "./series";
import { deriveNight, groupSleepNights } from "./sleep";

type Reading = SeriesPoint & { value: number };
export type TodayTrendOption = {
  id: string;
  title: string;
  unit: string | null;
  source: string;
  kind: "daily-total" | "nightly" | "daily-median";
  days: { date: string; value: number }[];
  latestAt: string | null;
};

// Keep the last canonical snapshot of each day, never sum or average snapshots.
export function dailyReadings(
  readings: Reading[],
): { date: string; value: number }[] {
  if (!hasOwnerDailyTotalSemantics(readings)) return dailyMedians(readings);
  const days = new Map<string, { date: string; value: number }>();
  for (const point of [...readings].sort(
    (a, b) => Date.parse(a.t) - Date.parse(b.t),
  )) {
    const date = new Date(point.t).toISOString().slice(0, 10);
    days.set(date, { date, value: point.value });
  }
  return [...days.values()];
}

// Windows end today, not at the last observation: stale data stays visibly stale.
export function trendWindow(
  days: TodayTrendOption["days"],
  count: number,
  now: string,
) {
  const end = Date.parse(`${now.slice(0, 10)}T00:00:00Z`);
  const start = end - (count - 1) * 86_400_000;
  return days.filter(
    ({ date }) => Date.parse(date) >= start && Date.parse(date) <= end,
  );
}

export function readingDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function findingEvidenceHref(id: number): string {
  return `/findings?finding=${id}#selected-finding`;
}

// A glance must never turn disagreement between devices into an average.
// Prefer the canonical daily total or primary stream; otherwise show the
// latest stream. The full source comparison remains available in the detail.
export function todayReadings(series: MetricSeries | null): Reading[] {
  if (!series) return [];
  const readings = series.points
    .filter(
      (point): point is Reading =>
        point.value !== null &&
        Number.isFinite(point.value) &&
        Number.isFinite(Date.parse(point.t)),
    )
    .sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
  if (hasOwnerDailyTotalSemantics(readings)) {
    return readings.filter(
      (point) => point.aggregation_scope === "owner_all_source_day_total",
    );
  }
  const primary = readings.filter((point) => point.is_primary);
  const candidates = primary.length > 0 ? primary : readings;
  const latest = candidates.at(-1);
  if (!latest) return [];
  return candidates.filter(
    (point) =>
      point.source_id === latest.source_id &&
      point.stream_id === latest.stream_id,
  );
}

export function dailyMedians(
  readings: Reading[],
): { date: string; value: number }[] {
  const days = new Map<string, number[]>();
  for (const point of readings) {
    const date = new Date(point.t).toISOString().slice(0, 10);
    const values = days.get(date) ?? [];
    values.push(point.value);
    days.set(date, values);
  }
  return [...days]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, values]) => {
      values.sort((a, b) => a - b);
      const middle = Math.floor(values.length / 2);
      return {
        date,
        value:
          values.length % 2
            ? values[middle]
            : (values[middle - 1] + values[middle]) / 2,
      };
    });
}

// Reuse the Sleep page's interval reconciliation when no duration series is
// supplied. Stage counts are never a substitute for actual sleep duration.
export function sleepDurationFromStages(
  series: MetricSeries | null,
): MetricSeries | null {
  if (!series) return null;
  const points = [...groupSleepNights(series.points)].flatMap(
    ([key, stages]) => {
      const night = deriveNight(key, stages);
      return night
        ? [
            {
              t: night.wakeTime,
              value: night.durationMin,
              code: null,
              unit: "min",
              source_id: "reconciled-sleep",
              stream_id: "reconciled-sleep",
              confidence: null,
            },
          ]
        : [];
    },
  );
  return {
    ...series,
    metric: {
      id: "sleep.duration",
      display_name: "Sleep",
      category: "sleep",
      value_type: "quantity",
      canonical_unit: "min",
    },
    points,
  };
}

export function todayFindings(findings: Finding[]): Finding[] {
  const latest = new Map<string, Finding>();
  for (const finding of [...findings].sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  )) {
    if (finding.finding_type === "recovery_score") continue;
    const key = `${finding.finding_type}:${finding.metric ?? finding.id}`;
    if (!latest.has(key)) latest.set(key, finding);
  }
  return groupFindingsForDisplay([...latest.values()])
    .flatMap((group) => group.findings)
    .slice(0, 3);
}
