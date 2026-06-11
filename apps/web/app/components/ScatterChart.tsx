// Day-aligned scatter for the Relationships explorer: one dot per shared UTC
// day, x = metric A's day mean, y = metric B's. Pure presentational — the page
// computes the pairs (lib/analytics alignDaily); this only draws them. Axis
// extents are printed verbatim so the dots are readable as data, not vibes.
import type { AlignedPair } from "../lib/analytics";

function fmt(v: number): string {
  const rounded = Math.abs(v) >= 100 ? Math.round(v) : Number(v.toFixed(1));
  return String(rounded);
}

export function ScatterChart({
  pairs,
  xLabel,
  yLabel,
}: {
  pairs: AlignedPair[];
  xLabel: string;
  yLabel: string;
}) {
  if (pairs.length < 2) {
    return <p className="empty">Not enough shared days to draw a scatter.</p>;
  }
  const xs = pairs.map((p) => p.a);
  const ys = pairs.map((p) => p.b);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const w = 600;
  const h = 240;
  const pad = 14; // keep edge dots fully inside the frame
  const px = (v: number) => pad + ((v - minX) / spanX) * (w - 2 * pad);
  const py = (v: number) => h - pad - ((v - minY) / spanY) * (h - 2 * pad);
  return (
    <figure className="scatter">
      <svg
        className="scatter-svg"
        viewBox={`0 0 ${w} ${h}`}
        role="img"
        aria-label={`Scatter: ${xLabel} vs ${yLabel}, ${pairs.length} shared days`}
      >
        <rect className="scatter-frame" x="0.5" y="0.5" width={w - 1} height={h - 1} rx="8" />
        {pairs.map((p) => (
          <circle key={p.day} className="scatter-dot" cx={px(p.a)} cy={py(p.b)} r="4">
            <title>{`${p.day}: ${fmt(p.a)}, ${fmt(p.b)}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="scatter-cap mono">
        <span>
          x · {xLabel} ({fmt(minX)}–{fmt(maxX)})
        </span>
        <span>
          y · {yLabel} ({fmt(minY)}–{fmt(maxY)})
        </span>
      </figcaption>
    </figure>
  );
}
