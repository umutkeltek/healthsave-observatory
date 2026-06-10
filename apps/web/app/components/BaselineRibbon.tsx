// The signature primitive: a recent trace drawn against the user's own baseline
// band, with anomaly pins where the value left the expected range. Reused in the
// hero, metric cards, and the README screenshot. SVG (band + median + trace) is
// stretched edge-to-edge; anomaly pins are HTML overlays so they stay perfectly
// round regardless of width.

import { HoverOverlay } from "./chart/HoverOverlay";
import { quantile } from "./chart/scale";

type Props = {
  values: number[];
  band?: [number, number]; // expected range (value units); defaults to P25–P75
  anomalies?: number[]; // indices into `values` to pin
  height?: number; // plot height in px
  axis?: [string, string]; // left / right captions
  live?: boolean; // last reading <24h — adds the slow mint freshness shimmer
  hoverLabels?: string[]; // per-value captions (dates) — enables the tooltip overlay
  unit?: string | null; // printed after the value in the tooltip
};

export function BaselineRibbon({
  values,
  band,
  anomalies = [],
  height = 76,
  axis,
  live,
  hoverLabels,
  unit,
}: Props) {
  if (values.length < 2) return null;

  const sorted = [...values].sort((a, b) => a - b);
  const lo = band ? band[0] : quantile(sorted, 0.25);
  const hi = band ? band[1] : quantile(sorted, 0.75);
  const min = Math.min(...values, lo);
  const max = Math.max(...values, hi);
  const span = max - min || 1;

  const W = 1000;
  const H = 100;
  const padY = 12;
  const x = (i: number) => (i / (values.length - 1)) * W;
  const y = (v: number) => padY + (H - 2 * padY) * (1 - (v - min) / span);

  const trace = values
    .map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
    .join(" ");
  const bandTop = y(hi);
  const bandBot = y(lo);
  const mid = y((lo + hi) / 2);

  return (
    <div className="ribbon-wrap">
      <div className={`ribbon-plot ${live ? "is-live" : ""}`} style={{ height }}>
        <svg
          className="ribbon"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label="Recent trace against your personal baseline range"
        >
          <rect
            className="ribbon-band"
            x="0"
            y={bandTop}
            width={W}
            height={Math.max(2, bandBot - bandTop)}
          />
          <line className="ribbon-band-edge" x1="0" y1={bandTop} x2={W} y2={bandTop} vectorEffect="non-scaling-stroke" />
          <line className="ribbon-band-edge" x1="0" y1={bandBot} x2={W} y2={bandBot} vectorEffect="non-scaling-stroke" />
          <line className="ribbon-median" x1="0" y1={mid} x2={W} y2={mid} vectorEffect="non-scaling-stroke" />
          <path className="ribbon-trace" d={trace} pathLength={1} vectorEffect="non-scaling-stroke" />
        </svg>
        {anomalies.map((i) => (
          <span
            key={i}
            className="ribbon-pin"
            style={{ left: `${(i / (values.length - 1)) * 100}%`, top: `${(y(values[i]) / H) * 100}%` }}
            aria-hidden
          />
        ))}
        {hoverLabels && hoverLabels.length === values.length && (
          <HoverOverlay
            points={values.map((v, i) => ({
              xPct: (i / (values.length - 1)) * 100,
              yPct: (y(v) / H) * 100,
              label: hoverLabels[i],
              value: `${Number(v.toFixed(1))}${unit ? ` ${unit}` : ""}`,
            }))}
          />
        )}
      </div>
      {axis && (
        <div className="ribbon-axis">
          <span>{axis[0]}</span>
          <span>{axis[1]}</span>
        </div>
      )}
    </div>
  );
}
