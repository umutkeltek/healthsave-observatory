// N labelled line series on one shared scale — extends MetricCard's single
// Sparkline to a multi-line overlay using the chart palette tokens. Pure
// presentational; the page reduces points into {label, values}[] via analytics.
const PALETTE = ["var(--accent)", "var(--signal)", "var(--experiment)", "var(--anomaly)"];

export type ChartSeries = { label: string; values: number[] };

function path(values: number[], min: number, span: number, w: number, h: number): string {
  if (values.length < 2) return "";
  const step = w / (values.length - 1);
  return values
    .map((v, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${(h - ((v - min) / span) * h).toFixed(1)}`)
    .join(" ");
}

export function MultiSeriesChart({ series }: { series: ChartSeries[] }) {
  const all = series.flatMap((s) => s.values);
  if (all.length < 2) {
    return <p className="empty">Not enough data to chart this comparison.</p>;
  }
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const w = 600;
  const h = 130;
  return (
    <div className="multi-chart">
      <svg className="multi-svg" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
        {series.map((s, i) => (
          <path
            key={s.label}
            d={path(s.values, min, span, w, h)}
            pathLength={1}
            fill="none"
            stroke={PALETTE[i % PALETTE.length]}
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
      </svg>
      <div className="multi-legend">
        {series.map((s, i) => (
          <span className="multi-legend-item" key={s.label}>
            <span className="multi-swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}
