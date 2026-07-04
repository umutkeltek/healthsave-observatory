import type { MetricSeries } from "../lib/api";
import { quantile } from "./chart/scale";
import { CountUp } from "./CountUp";

function numberLabel(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1000) return Math.round(value).toLocaleString();
  if (abs < 10 && !Number.isInteger(value)) return value.toFixed(1);
  return Math.round(value).toLocaleString();
}

function Sparkline({ values }: { values: number[] }) {
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
      <path d={d} pathLength={1} fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
      <circle
        className={`spark-dot ${outOfBand ? "out" : ""}`}
        cx={w}
        cy={y(last)}
        r="3.5"
        vectorEffect="non-scaling-stroke"
      />
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
  const deltaLabel = `${delta >= 0 ? "Higher" : "Lower"} by ${numberLabel(deltaAbs)}`;

  return (
    <article className="card metric-card">
      <div className="metric-card-head">
        <div>
          <h2>{series.metric.display_name}</h2>
          <span className="metric-kind">{series.range} window</span>
        </div>
        <span className={`metric-state ${delta >= 0 ? "up" : "down"}`}>{deltaLabel}</span>
      </div>

      <div className="metric-value-row">
        <div className="big">
          <CountUp value={Math.round(last)} />
          {series.metric.canonical_unit && <span className="unit">{series.metric.canonical_unit}</span>}
        </div>
        <div className="metric-mean">
          <span>range mean</span>
          <strong>{numberLabel(avg)}</strong>
        </div>
      </div>

      <div className="metric-chart-well">
        <Sparkline values={values} />
      </div>

      <div className="metric-foot">
        <span>{values.length.toLocaleString()} readings</span>
        <span>last {series.range}</span>
      </div>
    </article>
  );
}
