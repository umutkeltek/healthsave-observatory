import type { MetricSeries } from "../lib/api";
import { formatAgo, formatValue } from "../lib/format";
import {
  dailyReadings,
  readingDate,
  todayReadings,
  trendWindow,
} from "../lib/todayPresentation";
import { hasOwnerDailyTotalSemantics } from "../lib/series";
import { TodayReadingTile, TodayTileAffordance } from "./TodayExploration";
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
  const daily = trendWindow(
    dailyReadings(readings),
    7,
    new Date().toISOString(),
  );
  const unit = series?.metric.canonical_unit;
  const isSleep = id === "sleep.duration" && unit === "min";
  const isDailyTotal = hasOwnerDailyTotalSemantics(readings);
  const recentTotals = daily.slice(-7);
  const largestTotal = Math.max(1, ...recentTotals.map((point) => point.value));
  const sleepMinutes = Math.round(latest?.value ?? 0);
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

  const className = `today-metric today-metric-${tone}`;
  const contents = (
    <>
      <div className="today-metric-heading">
        <h2>{title}</h2>
        <TodayTileAffordance />
      </div>
      <div className="today-metric-reading">
        <strong>{value}</strong>
        {latest && <span>{displayUnit}</span>}
      </div>
      <div className="today-metric-chart" aria-hidden>
        {isDailyTotal && daily.length >= 2 ? (
          <div className="today-total-bars">
            {recentTotals.map((point, index) => (
              <span
                key={`${point.date}-${index}`}
                style={{
                  height: `${point.value > 0 ? Math.max(3, (point.value / largestTotal) * 100) : 0}%`,
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
              ? "More recent days will build a trend"
              : "No readings in the past 30 days"}
          </span>
        )}
      </div>
      <div className="today-metric-footer">
        {latest ? (
          <>
            <span>
              {isDailyTotal
                ? `Daily total · ${readingDate(latest.t)}`
                : "Latest reading"}
            </span>
            <time dateTime={latest.t}>{formatAgo(latest.t)}</time>
          </>
        ) : (
          <span>No recent data</span>
        )}
      </div>
    </>
  );
  return (
    <TodayReadingTile
      id={id}
      title={title}
      className={className}
      readingLabel={
        latest
          ? `${value} ${displayUnit ?? ""}. ${isDailyTotal ? `Daily total for ${readingDate(latest.t)} UTC` : `Latest reading ${formatAgo(latest.t)}`}`
          : "No recent readings"
      }
    >
      {contents}
    </TodayReadingTile>
  );
}
