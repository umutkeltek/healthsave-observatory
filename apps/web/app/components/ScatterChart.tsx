// Day-aligned scatter for the Relationships explorer: one dot per shared UTC
// day, x = metric A's day mean, y = metric B's. Pure presentational - the page
// computes the pairs (lib/analytics alignDaily); this only draws them. Now on a
// calibrated frame: real x/y axes (niceTicks), hairline gridlines, and value
// tick labels so the dots read as data, not vibes. SVG scales uniformly
// (height:auto), so its <text> stays undistorted.
import type { AlignedPair } from "../lib/analytics";
import { valueTicks } from "./chart/axis";

function fmt(v: number): string {
  const rounded = Math.abs(v) >= 100 ? Math.round(v) : Number(v.toFixed(1));
  return String(rounded);
}

const W = 520;
const H = 340;
const M = { l: 46, r: 16, t: 14, b: 34 };
const PLOT_W = W - M.l - M.r;
const PLOT_H = H - M.t - M.b;

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

  const xt = valueTicks(minX, maxX, 4);
  const yt = valueTicks(minY, maxY, 4);
  const loX = Math.min(minX, xt[0]?.value ?? minX);
  const hiX = Math.max(maxX, xt[xt.length - 1]?.value ?? maxX);
  const loY = Math.min(minY, yt[0]?.value ?? minY);
  const hiY = Math.max(maxY, yt[yt.length - 1]?.value ?? maxY);
  const spanX = hiX - loX || 1;
  const spanY = hiY - loY || 1;

  const px = (v: number) => M.l + ((v - loX) / spanX) * PLOT_W;
  const py = (v: number) => M.t + (1 - (v - loY) / spanY) * PLOT_H;

  return (
    <figure className="scatter">
      <svg
        className="scatter-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Scatter: ${xLabel} vs ${yLabel}, ${pairs.length} shared days`}
      >
        {/* horizontal gridlines + y tick labels */}
        {yt.map((t) => (
          <g key={`y${t.value}`}>
            <line
              className="chart-grid"
              x1={M.l}
              x2={W - M.r}
              y1={py(t.value)}
              y2={py(t.value)}
              vectorEffect="non-scaling-stroke"
            />
            <text className="scatter-tick" x={M.l - 6} y={py(t.value) + 3} textAnchor="end">
              {fmt(t.value)}
            </text>
          </g>
        ))}
        {/* vertical gridlines + x tick labels */}
        {xt.map((t) => (
          <g key={`x${t.value}`}>
            <line
              className="chart-grid"
              x1={px(t.value)}
              x2={px(t.value)}
              y1={M.t}
              y2={H - M.b}
              vectorEffect="non-scaling-stroke"
            />
            <text className="scatter-tick" x={px(t.value)} y={H - M.b + 15} textAnchor="middle">
              {fmt(t.value)}
            </text>
          </g>
        ))}
        <rect
          className="scatter-frame"
          x={M.l}
          y={M.t}
          width={PLOT_W}
          height={PLOT_H}
          vectorEffect="non-scaling-stroke"
        />
        {pairs.map((p) => (
          <circle key={p.day} className="scatter-dot" cx={px(p.a)} cy={py(p.b)} r="4">
            <title>{`${p.day}: ${fmt(p.a)}, ${fmt(p.b)}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="scatter-cap mono">
        <span>
          x · {xLabel} ({fmt(minX)}-{fmt(maxX)})
        </span>
        <span>
          y · {yLabel} ({fmt(minY)}-{fmt(maxY)})
        </span>
      </figcaption>
    </figure>
  );
}
