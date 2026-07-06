// The Body Dial — the hero's calibrated recovery instrument. A 240deg SVG arc
// gauge with engraved threshold ticks (every 5, majors every 25, labels at
// 0/50/100), a tertiary track, an optional grey "your recent normal" band
// segment, and a semantic fill whose share of the sweep is the score. Geometry
// is ported from the reference mock (docs_private/plans/2026-07-06-meridian-mock.html)
// and lives in chart/dialGeometry.ts (unit-tested there). Server-rendered SVG;
// only the fill sweep is a client island (DialFill). When there is no score
// the dial shows a bare track and a "—" readout — never a fake value. Colour
// comes from `--dial-color`, set by the `dial-tone-*` class.

import { CountUp } from "./CountUp";
import { arcPath, bandArc, R_ARC, TICKS } from "./chart/dialGeometry";
import { DialFill } from "./chart/DialFill";

export type DialTone = "good" | "warn" | "muted";

const FILL_D = arcPath(0, 1, R_ARC);

export function BodyDial({
  score,
  tone,
  caption = "Recovery",
  baselineBand,
}: {
  score: number | null;
  tone: DialTone;
  caption?: string;
  // Optional "recent normal" range in score units (0-100). Omitted honestly
  // when the hero has no baseline range for the score itself.
  baselineBand?: [number, number];
}) {
  const band = bandArc(baselineBand, R_ARC);

  return (
    <div className={`body-dial dial-tone-${tone}`}>
      <div className="body-dial-wrap">
        <svg
          viewBox="0 0 260 232"
          role="img"
          aria-label={score !== null ? `Recovery ${Math.round(score)} of 100` : "Recovery score building"}
        >
          {TICKS.map((tk) => (
            <line
              key={tk.i}
              className={`body-dial-tick${tk.major ? " major" : ""}`}
              x1={tk.x1.toFixed(2)}
              y1={tk.y1.toFixed(2)}
              x2={tk.x2.toFixed(2)}
              y2={tk.y2.toFixed(2)}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {TICKS.filter((tk) => tk.label).map((tk) => (
            <text
              key={`l${tk.i}`}
              className="body-dial-label"
              x={tk.label![0].toFixed(2)}
              y={(tk.label![1] + 3).toFixed(2)}
              textAnchor="middle"
            >
              {tk.i}
            </text>
          ))}
          <path className="body-dial-track" d={FILL_D} vectorEffect="non-scaling-stroke" />
          {band && <path className="body-dial-band" d={band} vectorEffect="non-scaling-stroke" />}
          {score !== null && <DialFill d={FILL_D} score={score} />}
        </svg>
        <div className="body-dial-readout">
          <div className="body-dial-num">{score !== null ? <CountUp value={score} duration={850} /> : "—"}</div>
          <div className="body-dial-cap">{caption}</div>
        </div>
      </div>
    </div>
  );
}
