import type { Delta } from "../lib/analytics";

export type Side = { label: string; value: number; meta?: string };

// A vs B with a delta between them — NEVER a single merged number. The delta is
// B relative to A; A and B are always shown verbatim. An optional caveat carries
// the comparability stance (e.g. SDNN vs RMSSD) from healthOpinion.
export function ComparisonCard({
  title,
  unit,
  a,
  b,
  delta,
  caveat,
  warn,
}: {
  title: string;
  unit: string;
  a: Side;
  b: Side;
  delta: Delta;
  caveat?: string | null;
  warn?: boolean;
}) {
  const dir = delta.direction;
  const sign = delta.abs > 0 ? "+" : "";
  return (
    <article className="card compare-card">
      <div className="cmp-head">
        <span className="card-title">{title}</span>
        {warn && <span className="badge cmp-warn">not directly comparable</span>}
      </div>
      <div className="cmp-cols">
        <div className="cmp-col">
          <span className="cmp-label">{a.label}</span>
          <span className="cmp-val">
            {a.value}
            <span className="cmp-unit">{unit}</span>
          </span>
          {a.meta && <span className="cmp-meta">{a.meta}</span>}
        </div>
        <div className={`cmp-delta ${dir}`}>
          <span className="cmp-delta-val">
            {sign}
            {delta.abs}
            {unit ? ` ${unit}` : ""}
          </span>
          {delta.pct !== null && (
            <span className="cmp-delta-pct">
              {sign}
              {delta.pct}%
            </span>
          )}
        </div>
        <div className="cmp-col">
          <span className="cmp-label">{b.label}</span>
          <span className="cmp-val">
            {b.value}
            <span className="cmp-unit">{unit}</span>
          </span>
          {b.meta && <span className="cmp-meta">{b.meta}</span>}
        </div>
      </div>
      {caveat && <p className="cmp-caveat">{caveat}</p>}
    </article>
  );
}
