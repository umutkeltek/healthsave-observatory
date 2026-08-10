import type { MetricSeries } from "../lib/api";
import { positiveIsGoodFor } from "../lib/direction";
import { formatValue } from "../lib/format";
import { rangeLabel } from "../lib/ranges";
import { quantile } from "./chart/scale";
import { CountUp } from "./CountUp";

function Sparkline({ values, unit, label }: { values: number[]; unit?: string; label: string }) {
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
      <circle
        className={`spark-dot ${outOfBand ? "out" : ""}`}
        cx={w}
        cy={y(last)}
        r="3.5"
        vectorEffect="non-scaling-stroke"
      >
        <title>{`${formatValue(last, unit)} · ${label}`}</title>
      </circle>
    </svg>
  );
}

export function MetricCard({
  series,
  fallbackTitle,
}: {
  series: MetricSeries | null;
  fallbackTitle: string;
}) {
  if (!series) {
    return (
      <article className="card metric-card metric-card-empty">
        <div className="metric-card-head">
          <h2>{fallbackTitle}</h2>
          <span className="metric-state">waiting</span>
        </div>
        <p className="empty">No readings in this range yet.</p>
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

  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  const delta = last - avg;
  const deltaAbs = Math.abs(delta);
  const deltaLabel = `${delta >= 0 ? "Higher" : "Lower"} by ${formatValue(deltaAbs)}`;
  // Tone reflects whether the move is good or bad, not just up or down: a rise
  // in resting HR should not read as positive. When the metric's direction is
  // unknown we stay neutral instead of guessing.
  const direction = positiveIsGoodFor(series.metric.id);
  const tone = direction === null ? "" : direction === (delta >= 0) ? "good" : "bad";

  return (
    <article className="card metric-card">
      <div className="metric-card-head">
        <div>
          <h2>{series.metric.display_name}</h2>
          <span className="metric-kind">{rangeLabel(series.range)} window</span>
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
