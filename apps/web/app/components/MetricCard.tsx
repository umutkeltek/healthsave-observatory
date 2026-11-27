import type { MetricSeries } from "../lib/api";
import { positiveIsGoodFor } from "../lib/direction";
import { formatValue } from "../lib/format";
import { metricOneLiner } from "../lib/metricNotes";
import { rangeLabel } from "../lib/ranges";
import { hasOwnerDailyTotalSemantics, sourceGroupLabel, splitBySource } from "../lib/series";
import { quantile } from "./chart/scale";
import { CountUp } from "./CountUp";

export function Sparkline({ values, unit, label }: { values: number[]; unit?: string; label: string }) {
  if (values.length < 2) return null;

  const sorted = [...values].sort((a, b) => a - b);
  const lo = quantile(sorted, 0.25);
  const hi = quantile(sorted, 0.75);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 220;
  const h = 54;
  const pad = 5;
  const step = w / (values.length - 1);
  const y = (v: number) => pad + (h - 2 * pad) * (1 - (v - min) / span);
  const d = values
    .map((v, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${y(v).toFixed(1)}`)
    .join(" ");
  const last = values[values.length - 1];
  const outOfBand = last < lo || last > hi;
  const bandTop = y(hi);
  const bandHeight = Math.max(2, y(lo) - bandTop);

  return (
    <svg className="spark signal-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      <rect className="spark-band" x="0" y={bandTop} width={w} height={bandHeight} />
      <path d={d} pathLength={1} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      {/* A zero-length round-capped stroke stays round in the stretched
          viewBox; a <circle> was squashed into a wide ellipse. */}
      <path
        className={`spark-dot ${outOfBand ? "out" : ""}`}
        d={`M ${w} ${y(last).toFixed(1)} h 0`}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      >
        <title>{`${formatValue(last, unit)} · ${label}`}</title>
      </path>
    </svg>
  );
}

export function MetricCard({
  series,
  fallbackTitle,
  missing = false,
  sourceLabels = {},
}: {
  series: MetricSeries | null;
  fallbackTitle: string;
  // The backend answered that it does not know this metric (404).
  missing?: boolean;
  // Device name per stream id (or source id), for a metric two devices report.
  sourceLabels?: Record<string, string>;
}) {
  // No series means the read failed (an answered empty range is a series with
  // no points, handled below) - not "no readings yet".
  if (!series) {
    return (
      <article className="card metric-card metric-card-empty">
        <div className="metric-card-head">
          <h2>{fallbackTitle}</h2>
          <span className="metric-state">{missing ? "not found" : "no answer"}</span>
        </div>
        <p className="empty">
          {missing ? "This Observatory does not know this signal." : "The Observatory API did not answer for this signal."}
        </p>
      </article>
    );
  }

  const values = series.points.map((p) => p.value).filter((v): v is number => v !== null);
  const last = values.at(-1);

  if (last === undefined) {
    return (
      <article className="card metric-card metric-card-empty">
        <div className="metric-card-head">
          <h2>{series.metric.display_name}</h2>
          <span className="metric-state">waiting</span>
        </div>
        <p className="empty">No numeric readings in this range.</p>
      </article>
    );
  }

  // Two devices reporting one metric are two readings: one block each, with
  // its own value, mean and line. Never one averaged series (healthOpinion.ts).
  const groups = hasOwnerDailyTotalSemantics(series.points) ? [] : splitBySource(series.points);
  if (groups.length > 1) {
    const unit = series.metric.canonical_unit ?? undefined;
    const note = metricOneLiner(series.metric.id);
    return (
      <article className="card metric-card">
        <div className="metric-card-head">
          <div>
            <h2>{series.metric.display_name}</h2>
            <span className="metric-kind">{rangeLabel(series.range)} window</span>
            {note && (
              <>
                <br />
                <span className="metric-kind">{note}</span>
              </>
            )}
          </div>
          <span className="metric-state">{groups.length} sources</span>
        </div>
        {groups.map((group, index) => {
          const groupValues = group.points.map((p) => p.value);
          const mean = groupValues.reduce((a, b) => a + b, 0) / groupValues.length;
          const label = sourceGroupLabel(group, sourceLabels, index);
          return (
            <div key={group.key} aria-label={`${label}: ${formatValue(group.latest.value)} ${unit ?? ""}`}>
              <span className="metric-kind">{label}</span>
              <div className="metric-value-row">
                <div className="big">
                  <CountUp value={Math.round(group.latest.value)} />
                  {unit && <span className="unit">{unit}</span>}
                </div>
                <div className="metric-mean">
                  <span>{label} mean</span>
                  <strong>{formatValue(mean)}</strong>
                </div>
              </div>
              <div className="metric-chart-well">
                <Sparkline values={groupValues} unit={unit} label={`${label}: latest of ${groupValues.length} readings`} />
              </div>
            </div>
          );
        })}
        <div className="metric-foot">
          <span>Each device against its own readings, never averaged</span>
          <span>last {rangeLabel(series.range)}</span>
        </div>
      </article>
    );
  }

  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  const delta = last - avg;
  const deltaAbs = Math.abs(delta);
  const deltaLabel = `${delta >= 0 ? "Higher" : "Lower"} by ${formatValue(deltaAbs)}`;
  // Tone reflects whether the move is good or bad, not just up or down: a rise
  // in resting HR should not read as positive. When the metric's direction is
  // unknown we stay neutral instead of guessing.
  const direction = positiveIsGoodFor(series.metric.id);
  const note = metricOneLiner(series.metric.id);
  const tone = direction === null ? "" : direction === (delta >= 0) ? "good" : "bad";

  return (
    <article className="card metric-card">
      <div className="metric-card-head">
        <div>
          <h2>{series.metric.display_name}</h2>
          <span className="metric-kind">{rangeLabel(series.range)} window</span>
          {note && (
            <>
              <br />
              <span className="metric-kind">{note}</span>
            </>
          )}
        </div>
        <span className={`metric-state${tone ? ` ${tone}` : ""}`}>{deltaLabel}</span>
      </div>

      <div className="metric-value-row">
        <div className="big">
          <CountUp value={Math.round(last)} />
          {series.metric.canonical_unit && <span className="unit">{series.metric.canonical_unit}</span>}
        </div>
        <div className="metric-mean">
          <span>range mean</span>
          <strong>{formatValue(avg)}</strong>
        </div>
      </div>

      <div className="metric-chart-well">
        <Sparkline values={values} unit={series.metric.canonical_unit ?? undefined} label={`latest of ${values.length} readings`} />
      </div>

      <div className="metric-foot">
        <span>{values.length.toLocaleString()} readings</span>
        <span>last {rangeLabel(series.range)}</span>
      </div>
    </article>
  );
}
