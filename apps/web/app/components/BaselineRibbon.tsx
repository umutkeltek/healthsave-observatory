// The signature primitive: a recent trace drawn against the user's own baseline
// band, with anomaly pins where the value left the expected range. Reused in the
// hero, metric cards, and the README screenshot. SVG (band + median + trace) is
// stretched edge-to-edge; anomaly pins are HTML overlays so they stay perfectly
// round regardless of width.

import { valueTicks } from "./chart/axis";
import type { ScrubSeries } from "./chart/dayScrub";
import { ScrubCursor } from "./chart/DayRuler";
import { HoverOverlay } from "./chart/HoverOverlay";
import { quantile, robustDomain } from "./chart/scale";
import { formatTick } from "../lib/format";

type Props = {
  values: number[];
  band?: [number, number]; // expected range (value units); defaults to P25-P75
  anomalies?: number[]; // indices into `values` to pin
  height?: number; // plot height in px
  axis?: [string, string]; // left / right captions
  live?: boolean; // last reading <24h - adds the slow mint freshness shimmer
  hoverLabels?: string[]; // per-value captions (dates) - enables the tooltip overlay
  timestamps?: string[]; // Real-time x positions aligned with values.
  unit?: string | null; // printed after the value in the tooltip
  ariaLabel?: string; // SVG accessible name; override so repeated figures aren't identical to AT
  // One slot per calendar day, read with the day ruler (DayRuler.tsx) instead
  // of the hover tooltip. Days without a reading are gaps in the line. Replaces
  // `values`, `band`, `timestamps` and the left value gutter: the usual range is
  // labelled on the band itself.
  scrub?: ScrubSeries;
};

export function BaselineRibbon({
  values,
  band,
  anomalies = [],
  height = 76,
  axis,
  live,
  hoverLabels,
  timestamps,
  unit,
  ariaLabel = "Recent trace against your personal baseline range",
  scrub,
}: Props) {
  if (scrub) return <DailyRibbon series={scrub} height={height} ariaLabel={ariaLabel} />;
  if (values.length < 2) return null;

  const sorted = [...values].sort((a, b) => a - b);
  const lo = band ? band[0] : quantile(sorted, 0.25);
  const hi = band ? band[1] : quantile(sorted, 0.75);
  // Robust p2-p98 domain widened to hold the baseline band — so a few HRV
  // spikes can't flatten the trace into a hairline or push the band off-scale.
  const [min, max] = robustDomain(values, lo, hi);
  const span = max - min || 1;

  const W = 1000;
  const H = 100;
  const padY = 12;
  const times = timestamps?.length === values.length ? timestamps.map(Date.parse) : null;
  const timed = times !== null && times.every(Number.isFinite) && times.at(-1)! > times[0];
  const x = (i: number) => timed
    ? ((times![i] - times![0]) / (times!.at(-1)! - times![0])) * W
    : (i / (values.length - 1)) * W;
  // Clamp into the domain so outliers pin at the top/bottom edge of the plot.
  const clampV = (v: number) => (v < min ? min : v > max ? max : v);
  const y = (v: number) => padY + (H - 2 * padY) * (1 - (clampV(v) - min) / span);

  const trace = values
    .map((v, i) => `${i === 0 || (timed && times![i] - times![i - 1] > 36 * 3_600_000) ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`)
    .join(" ");
  const bandTop = y(hi);
  const bandBot = y(lo);
  const mid = y((lo + hi) / 2);
  const yTicks = valueTicks(min, max, 3);

  return (
    <div className="ribbon-wrap">
      <div className="ribbon-frame">
        <div className="ribbon-yaxis" style={{ height }} aria-hidden>
          {unit ? (
            <span className="chart-tick-label ribbon-unit">{unit}</span>
          ) : null}
          {yTicks.map((t) => (
            <span
              key={t.value}
              className="chart-tick-label ribbon-y-label"
              style={{ top: `${(y(t.value) / H) * 100}%` }}
            >
              {formatTick(t.value)}
            </span>
          ))}
        </div>
        <div className={`ribbon-plot ${live ? "is-live" : ""}`} style={{ height }}>
        <svg
          className="ribbon"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={ariaLabel}
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
          <path className="ribbon-trace" d={trace} vectorEffect="non-scaling-stroke" />
        </svg>
        {anomalies.map((i) => (
          <span
            key={i}
            className="ribbon-pin"
            style={{ left: `${x(i) / W * 100}%`, top: `${(y(values[i]) / H) * 100}%` }}
            aria-hidden
          />
        ))}
        {hoverLabels && hoverLabels.length === values.length && (
          <HoverOverlay
            points={values.map((v, i) => ({
              xPct: x(i) / W * 100,
              yPct: (y(v) / H) * 100,
              label: hoverLabels[i],
              value: `${Number(v.toFixed(1))}${unit ? ` ${unit}` : ""}`,
            }))}
          />
        )}
        </div>
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

// The per-day variant. x is the day's slot in the calendar window, so the
// line and the ruler's ticks share one scale; a missing day breaks the line
// and is never bridged.
function DailyRibbon({
  series,
  height,
  ariaLabel,
}: {
  series: ScrubSeries;
  height: number;
  ariaLabel: string;
}) {
  const days = series.days;
  const finite = days.flatMap((day) => (day.value === null ? [] : [day.value]));
  if (finite.length === 0) return null;
  const sorted = [...finite].sort((a, b) => a - b);
  const [lo, hi] = series.band ?? [quantile(sorted, 0.25), quantile(sorted, 0.75)];
  const [min, max] = robustDomain(finite, lo, hi);
  const span = max - min || 1;

  const W = 1000;
  const H = 100;
  // Room under the trace for the selected day's stem to reach the ruler.
  const padTop = 12;
  const padBottom = 24;
  const n = days.length;
  const x = (i: number) => (n > 1 ? (i / (n - 1)) * W : W / 2);
  const clampV = (v: number) => (v < min ? min : v > max ? max : v);
  const y = (v: number) => padTop + (H - padTop - padBottom) * (1 - (clampV(v) - min) / span);

  const trace = days
    .map((day, i) =>
      day.value === null
        ? ""
        : `${i === 0 || days[i - 1].value === null ? "M" : "L"} ${x(i).toFixed(1)} ${y(day.value).toFixed(1)}`,
    )
    .filter(Boolean)
    .join(" ");
  // A reading with a gap on both sides has no segment to draw; mark it.
  const lone = days.flatMap((day, i) =>
    day.value !== null && days[i - 1]?.value == null && days[i + 1]?.value == null ? [i] : [],
  );
  const bandTop = y(hi);
  const bandBot = y(lo);
  const mid = y((lo + hi) / 2);
  const pct = (v: number, of: number) => `${((v / of) * 100).toFixed(2)}%`;

  return (
    <div className="ribbon-wrap ribbon-daily">
      <div className="ribbon-plot" style={{ height }}>
        <svg
          className="ribbon"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={ariaLabel}
        >
          {days.map((day, i) =>
            day.weekStart ? (
              <line
                key={day.date}
                className="ribbon-week"
                x1={x(i)}
                x2={x(i)}
                y1={0}
                y2={H}
                vectorEffect="non-scaling-stroke"
              />
            ) : null,
          )}
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
          <path className="ribbon-trace" d={trace} vectorEffect="non-scaling-stroke" />
        </svg>
        {series.usual && (
          <>
            <span className="ribbon-edge-label is-top" style={{ top: pct(bandTop, H) }} aria-hidden>
              {series.usual[1]}
            </span>
            <span className="ribbon-edge-label is-bottom" style={{ top: pct(bandBot, H) }} aria-hidden>
              {series.usual[0]}
            </span>
          </>
        )}
        {lone.map((i) => (
          <span
            key={days[i].date}
            className="ribbon-lone"
            style={{ left: pct(x(i), W), top: pct(y(days[i].value as number), H) }}
            aria-hidden
          />
        ))}
        <ScrubCursor
          points={days.map((day, i) => ({
            x: (x(i) / W) * 100,
            y: day.value === null ? null : (y(day.value) / H) * 100,
          }))}
        />
      </div>
    </div>
  );
}
