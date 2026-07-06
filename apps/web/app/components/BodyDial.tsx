// The Body Dial — the hero's calibrated recovery instrument. A 240deg SVG arc
// gauge with engraved threshold ticks (every 5, majors every 25, labels at
// 0/50/100), a tertiary track, an optional grey "your recent normal" band
// segment, and a semantic fill whose share of the sweep is the score. Geometry
// is ported from the reference mock (docs_private/plans/2026-07-06-meridian-mock.html).
// Server-rendered SVG; only the fill sweep is a client island (DialFill). When
// there is no score the dial shows a bare track and a "—" readout — never a fake
// value. Colour comes from `--dial-color`, set by the `dial-tone-*` class.

import { CountUp } from "./CountUp";
import { DialFill } from "./chart/DialFill";

export type DialTone = "good" | "warn" | "muted";

const C = { x: 130, y: 128, r: 100 };
const R_ARC = C.r - 5;
const A0 = 210; // sweep start angle (deg)
const A1 = -30; // sweep end angle (deg)

function ang(t: number): number {
  return ((A0 + (A1 - A0) * t) * Math.PI) / 180;
}
function pt(t: number, r: number): [number, number] {
  return [C.x + Math.cos(ang(t)) * r, C.y - Math.sin(ang(t)) * r];
}
function arcPath(t0: number, t1: number, r: number): string {
  const [x0, y0] = pt(t0, r);
  const [x1, y1] = pt(t1, r);
  const large = Math.abs(t1 - t0) * 240 > 180 ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

// Engraved tick marks every 5 units; majors (every 25) longer + heavier.
const TICKS = Array.from({ length: 21 }, (_, k) => k * 5).map((i) => {
  const t = i / 100;
  const major = i % 25 === 0;
  const [x1, y1] = pt(t, C.r + 2);
  const [x2, y2] = pt(t, C.r + (major ? 11 : 6));
  const label = i % 50 === 0 ? pt(t, C.r + 22) : null;
  return { i, major, x1, y1, x2, y2, label };
});

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
  const bandArc =
    baselineBand &&
    Number.isFinite(baselineBand[0]) &&
    Number.isFinite(baselineBand[1]) &&
    baselineBand[1] > baselineBand[0]
      ? arcPath(
          Math.max(0, Math.min(1, baselineBand[0] / 100)),
          Math.max(0, Math.min(1, baselineBand[1] / 100)),
          R_ARC,
        )
      : null;

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
          <path className="body-dial-track" d={arcPath(0, 1, R_ARC)} vectorEffect="non-scaling-stroke" />
          {bandArc && <path className="body-dial-band" d={bandArc} vectorEffect="non-scaling-stroke" />}
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
