import Link from "next/link";
import type { MetricSeries } from "../lib/api";
import { formatAgo, formatValue } from "../lib/format";
import { dailyMedians, todayReadings } from "../lib/todayPresentation";
import { hasOwnerDailyTotalSemantics } from "../lib/series";
import { Sparkline } from "./MetricCard";

export function TodayMetricCard({
  series,
  id,
  title,
}: {
  series: MetricSeries | null;
  id: string;
  title: string;
}) {
  const readings = todayReadings(series);
  const latest = readings.at(-1);
  const daily = dailyMedians(readings);
  const unit = series?.metric.canonical_unit;
  const isSleep = id === "sleep.duration" && unit === "min";
  const isDailyTotal = hasOwnerDailyTotalSemantics(readings);
  const recentTotals = readings.slice(-7);
  const largestTotal = Math.max(1, ...recentTotals.map((point) => point.value));
  const average = readings.length
    ? readings.reduce((sum, point) => sum + point.value, 0) / readings.length
    : null;
  const sleepMinutes = Math.round(latest?.value ?? 0);
  const averageMinutes = Math.round(average ?? 0);
  const value = latest
    ? isSleep
      ? Math.floor(sleepMinutes / 60)
      : formatValue(latest.value)
    : "—";
  const displayUnit = isSleep
    ? `h ${sleepMinutes % 60}m`
    : id === "activity.steps" && unit === "count"
      ? "steps"
      : unit === "breaths/min"
        ? "br/min"
        : unit;
  const tone = id.startsWith("sleep.")
    ? "sleep"
    : id.startsWith("activity.")
      ? "activity"
      : "vital";

  return (
    <Link
      href={
        id === "sleep.duration"
          ? "/sleep"
          : `/library/${encodeURIComponent(id)}`
      }
      className={`today-metric today-metric-${tone}`}
    >
      <div className="today-metric-heading">
        <h2>{title}</h2>
        <span aria-hidden>↗</span>
      </div>
      <div className="today-metric-reading">
        <strong>{value}</strong>
        {latest && <span>{displayUnit}</span>}
      </div>
      <div className="today-metric-chart" aria-hidden>
        {isDailyTotal && readings.length >= 2 ? (
          <div className="today-total-bars">
            {recentTotals.map((point, index) => (
              <span
                key={`${point.t}-${index}`}
                style={{
                  height: `${point.value > 0 ? Math.max(3, point.value / largestTotal * 100) : 0}%`,
                }}
              />
            ))}
          </div>
        ) : daily.length >= 2 ? (
          <Sparkline
            values={daily.map((day) => day.value)}
            label="Daily median (UTC)"
          />
        ) : (
          <span className="today-metric-empty">
            {latest
              ? "More readings will build a trend"
              : "No readings in the past 7 days"}
          </span>
        )}
      </div>
      <div className="today-metric-footer">
        <span>{latest ? formatAgo(latest.t) : "Waiting for data"}</span>
        {average !== null && (
          <span
            title={
              isDailyTotal
                ? "Average of recorded daily totals; the latest day may be incomplete"
                : "7-day average from the displayed source; sparkline shows daily medians in UTC"
            }
          >
            Avg{" "}
            {isSleep
              ? `${Math.floor(averageMinutes / 60)}h ${averageMinutes % 60}m`
              : formatValue(average, unit === "count" ? null : unit)}
          </span>
        )}
      </div>
    </Link>
  );
}
