// One blood marker over time, each result drawn against ITS OWN lab's printed
// range (a band, not a line). Labs keep their own colour and their own line;
// nothing is averaged or joined across labs. Points are HTML overlays so they
// stay round at any width (the BaselineRibbon pattern). Server-rendered; the
// native title tooltip carries date, value, lab and band verdict.
import type { LabResult } from "../lib/api";
import { formatTick } from "../lib/format";
import {
  BAND_SHORT,
  CHART_H,
  CHART_W,
  bandTone,
  labChartGeometry,
  labDate,
  labValue,
} from "../lib/labs";
import { valueTicks } from "./chart/axis";

type Props = {
  results: LabResult[];
  streamOrder: string[];
  height?: number;
  compact?: boolean;
  ariaLabel: string;
};

export function LabChart({ results, streamOrder, height = 180, compact = false, ariaLabel }: Props) {
  const geometry = labChartGeometry(results, streamOrder);
  if (!geometry) return results.length ? <p className="muted">These results cannot be plotted on a comparable numeric axis. Read the recorded values below.</p> : null;
  const { points, bands, lines, min, max } = geometry;
  const toPct = (v: number) => ((CHART_H - 10 - (CHART_H - 20) * ((v - min) / (max - min))) / CHART_H) * 100;
  const ticks = compact ? [] : valueTicks(min, max, 4);
  const unit = points.at(-1)?.result.display_unit ?? "";

  return (
    <div className={`labs-chart${compact ? " is-compact" : ""}`}>
      {!compact && (
        <div className="labs-chart-yaxis" style={{ height }} aria-hidden>
          <span className="chart-tick-label labs-chart-unit">{unit}</span>
          {ticks.map((t) => (
            <span key={t.value} className="chart-tick-label labs-chart-tick" style={{ top: `${toPct(t.value)}%` }}>
              {formatTick(t.value)}
            </span>
          ))}
        </div>
      )}
      <div className="labs-chart-plot" style={{ height }}>
        <svg
          className="labs-chart-svg"
          viewBox={`0 0 ${CHART_W} ${CHART_H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={ariaLabel}
        >
          {bands.map((band) => (
            <rect
              key={`${band.x0}-${band.series}`}
              className="labs-band"
              x={band.x0}
              y={band.y0}
              width={Math.max(1, band.x1 - band.x0)}
              height={Math.max(1, band.y1 - band.y0)}
            />
          ))}
          {bands.map((band) => (
            <g key={`edge-${band.x0}-${band.series}`} className="labs-band-edge">
              {band.topEdge && (
                <line x1={band.x0} y1={band.y0} x2={band.x1} y2={band.y0} vectorEffect="non-scaling-stroke" />
              )}
              {band.bottomEdge && (
                <line x1={band.x0} y1={band.y1} x2={band.x1} y2={band.y1} vectorEffect="non-scaling-stroke" />
              )}
            </g>
          ))}
          {lines.map((line) => (
            <path
              key={line.d}
              className={`labs-line labs-s${line.series}`}
              d={line.d}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
        {points.map((point) => (
          <span
            key={point.result.id}
            className={`labs-dot labs-s${point.series}${bandTone(point.result.band) === "out" ? " is-out" : ""}`}
            style={{ left: `${(point.x / CHART_W) * 100}%`, top: `${(point.y / CHART_H) * 100}%` }}
            title={`${labDate(point.result.specimen_at)} · ${labValue(point.result)} · ${point.result.lab} (${BAND_SHORT[point.result.band]})`}
          />
        ))}
      </div>
      {!compact && results.length > 0 && (
        <div className="labs-chart-xaxis" aria-hidden>
          <span>{labDate(points[0].result.specimen_at)}</span>
          {points.length > 1 && <span>{labDate(points.at(-1)!.result.specimen_at)}</span>}
        </div>
      )}
      {geometry.omitted > 0 && <p className="labs-chart-note">{geometry.omitted} result{geometry.omitted === 1 ? " is" : "s are"} omitted from the chart: limits, unverified units, or different units. Recorded values remain in the table.</p>}
    </div>
  );
}
