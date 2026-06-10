import type { MetricSeries } from "../lib/api";
import { CountUp } from "./CountUp";

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 220;
  const h = 44;
  const step = w / (values.length - 1);
  const d = values
    .map((v, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${(h - ((v - min) / span) * h).toFixed(1)}`)
    .join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      <path d={d} pathLength={1} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
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
      <article className="card">
        <h2>{fallbackTitle}</h2>
        <p className="empty">Backend unreachable — start HealthSave Observatory and sync from the app.</p>
      </article>
    );
  }

  const values = series.points
    .map((p) => p.value)
    .filter((v): v is number => v !== null);
  const last = values.at(-1);

  if (last === undefined) {
    return (
      <article className="card">
        <h2>{series.metric.display_name}</h2>
        <p className="empty">No data yet — sync from HealthSave to populate this.</p>
      </article>
    );
  }

  const avg = values.reduce((a, b) => a + b, 0) / values.length;
  const delta = last - avg;

  return (
    <article className="card">
      <h2>{series.metric.display_name}</h2>
      <div className="big">
        <CountUp value={Math.round(last)} />
        <span className="unit">{series.metric.canonical_unit}</span>
      </div>
      <div className={`delta ${delta >= 0 ? "up" : "down"}`}>
        {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(0)} vs {series.range} average
      </div>
      <Sparkline values={values} />
      <div className="meta">
        {values.length} readings · last {series.range}
      </div>
    </article>
  );
}
