// N labelled line series on one calibrated scale. Extends MetricCard's single
// Sparkline to a multi-line overlay with a real coordinate system: fixed viewBox
// + margins, non-scaling strokes (no more preserveAspectRatio="none" stretch),
// a value y-axis (niceTicks), hairline gridlines, an optional dated x-axis, and
// direct end-labels for <=3 series. Axis TEXT is an HTML overlay positioned by %
// so it stays crisp at any container width (the SVG scales uniformly with
// height:auto, so % maps linearly onto user space); the geometry stays server-
// rendered inline SVG. The page reduces points into {label, values}[].
// Categorical series palette — distinct hues so overlaid/compared lines stay
// tellable apart (accent and signal are both system blue, so never pair them).
import { dateDomainMs, dateTicks, declutterLabels, valueTicks } from "./chart/axis";
import { niceTicks } from "./chart/scale";
import { timedDomain, timedSegments, type TimedPoint } from "./chart/timedSeries";

const PALETTE = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
];

export type ChartSeries = { label: string; points: TimedPoint[] };

// viewBox coordinate system (uniform scaling; the SVG renders at height:auto).
const RW = 720;
const RH = 240;
const M = { l: 46, r: 58, t: 16, b: 26 };
const PLOT_W = RW - M.l - M.r;
const PLOT_H = RH - M.t - M.b;
// Minimum vertical separation between end-labels, in viewBox user units. ~14px
// once the 720x240 viewBox is scaled down to a typical Explore panel width.
const END_LABEL_MIN_GAP = 22;

function fmtTick(v: number): string {
  const a = Math.abs(v);
  if (a >= 1000) return Math.round(v).toLocaleString();
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(a < 1 ? 2 : 1);
}

function path(points: TimedPoint[], lo: number, hi: number, startMs: number, endMs: number): string {
  if (points.length < 2) return "";
  const valueSpan = hi - lo || 1;
  const timeSpan = endMs - startMs || 1;
  const y = (v: number) => M.t + (1 - (v - lo) / valueSpan) * PLOT_H;
  return points
    .map((point, i) => {
      const x = M.l + ((Date.parse(point.t) - startMs) / timeSpan) * PLOT_W;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y(point.value).toFixed(1)}`;
    })
    .join(" ");
}

export function MultiSeriesChart({
  series,
  unit,
  dateDomain,
}: {
  series: ChartSeries[];
  unit?: string | null;
  dateDomain?: [string, string];
}) {
  const all = series.flatMap((s) => s.points.map((point) => point.value));
  if (all.length < 2) {
    return <p className="empty">Not enough data to chart this comparison.</p>;
  }
  const resolvedDomain = dateDomain ?? timedDomain(series);
  const domainMs = dateDomainMs(resolvedDomain);
  if (!domainMs) {
    return <p className="empty">These readings do not have a usable shared time range.</p>;
  }
  const [startMs, endMs] = domainMs;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const yt = niceTicks(min, max, 4);
  const lo = Math.min(min, yt[0]);
  const hi = Math.max(max, yt[yt.length - 1]);
  const span = hi - lo || 1;
  const yTicks = valueTicks(lo, hi, 4);

  const xTicks = dateTicks(startMs, endMs);

  const direct = series.length <= 3;
  const yUser = (v: number) => M.t + (1 - (v - lo) / span) * PLOT_H;

  // Direct end-labels only make sense for 2-3 overlaid series: a single series'
  // label would just duplicate the panel title, and >3 gets a legend instead.
  const showEndLabels = series.length >= 2 && series.length <= 3;
  const endLabels = showEndLabels
    ? series.flatMap((s, i) => {
        const last = [...s.points].sort((a, b) => Date.parse(a.t) - Date.parse(b.t)).at(-1);
        return last ? [{ label: s.label, color: PALETTE[i % PALETTE.length], y: yUser(last.value) }] : [];
      })
    : [];
  // Push apart any labels that would otherwise stack on top of each other.
  const endLabelY = declutterLabels(
    endLabels.map((e) => e.y),
    END_LABEL_MIN_GAP,
    M.t,
    M.t + PLOT_H,
  );
  const plotRightPct = ((M.l + PLOT_W) / RW) * 100;

  return (
    <div className="multi-chart">
      <div className="multi-plot">
        <svg
          className="multi-svg"
          viewBox={`0 0 ${RW} ${RH}`}
          role="img"
          aria-label={`Comparison chart: ${series.map((s) => s.label).join(" vs ")}`}
        >
          {yTicks.map((t) => (
            <line
              key={`g${t.value}`}
              className="chart-grid"
              x1={M.l}
              x2={RW - M.r}
              y1={yUser(t.value)}
              y2={yUser(t.value)}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {series.flatMap((s, i) =>
            timedSegments(s.points)
              .filter((segment) => segment.length >= 2)
              .map((segment, segmentIndex) => (
                <path
                  key={`${s.label}-${segmentIndex}`}
                  d={path(segment, lo, hi, startMs, endMs)}
                  pathLength={1}
                  fill="none"
                  stroke={PALETTE[i % PALETTE.length]}
                  strokeWidth="1.6"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                />
              )),
          )}
          {direct &&
            series.map((s, i) => {
              const last = [...s.points].sort((a, b) => Date.parse(a.t) - Date.parse(b.t)).at(-1);
              if (!last) return null;
              const cx = M.l + ((Date.parse(last.t) - startMs) / (endMs - startMs || 1)) * PLOT_W;
              return (
                <circle
                  key={`d${s.label}`}
                  cx={cx}
                  cy={yUser(last.value)}
                  r="2.6"
                  fill={PALETTE[i % PALETTE.length]}
                />
              );
            })}
        </svg>
        <div className="multi-axis" aria-hidden>
          {unit ? (
            <span
              className="chart-tick-label chart-axis-unit"
              style={{ left: `${((M.l - 7) / RW) * 100}%`, top: `${((M.t - 9) / RH) * 100}%` }}
            >
              {unit}
            </span>
          ) : null}
          {yTicks.map((t) => (
            <span
              key={`yl${t.value}`}
              className="chart-tick-label chart-y-label"
              style={{ left: `${((M.l - 7) / RW) * 100}%`, top: `${(yUser(t.value) / RH) * 100}%` }}
            >
              {fmtTick(t.value)}
            </span>
          ))}
          {xTicks.map((t, i) => (
            <span
              key={`xl${i}`}
              className="chart-tick-label chart-x-label"
              style={{
                left: `${((M.l + t.frac * PLOT_W) / RW) * 100}%`,
                top: `${((RH - M.b + 13) / RH) * 100}%`,
              }}
            >
              {t.label}
            </span>
          ))}
          {endLabels.map((e, k) => (
            <span
              key={`el${e.label}`}
              className="chart-end-label"
              style={{
                top: `${(endLabelY[k] / RH) * 100}%`,
                left: `${plotRightPct}%`,
                color: e.color,
              }}
            >
              {e.label}
            </span>
          ))}
        </div>
      </div>
      {!direct && (
        <div className="multi-legend">
          {series.map((s, i) => (
            <span className="multi-legend-item" key={s.label}>
              <span className="multi-swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
