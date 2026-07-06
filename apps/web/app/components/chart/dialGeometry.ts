// Pure trig + tick/band geometry for the Body Dial gauge (BodyDial.tsx).
// Extracted so the math is unit-testable without rendering SVG. Geometry is
// ported from the reference mock
// (docs_private/plans/2026-07-06-meridian-mock.html) — constants match the
// original inline BodyDial implementation verbatim. Unit-tested in
// dialGeometry.test.ts.

export const DIAL_CENTER = { x: 130, y: 128, r: 100 };
export const R_ARC = DIAL_CENTER.r - 5;
export const A0 = 210; // sweep start angle (deg)
export const A1 = -30; // sweep end angle (deg)

export function ang(t: number): number {
  return ((A0 + (A1 - A0) * t) * Math.PI) / 180;
}

export function pt(t: number, r: number): [number, number] {
  return [DIAL_CENTER.x + Math.cos(ang(t)) * r, DIAL_CENTER.y - Math.sin(ang(t)) * r];
}

export function arcPath(t0: number, t1: number, r: number): string {
  const [x0, y0] = pt(t0, r);
  const [x1, y1] = pt(t1, r);
  const large = Math.abs(t1 - t0) * 240 > 180 ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

export type DialTick = {
  i: number;
  major: boolean;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  label: [number, number] | null;
};

// Engraved tick marks every 5 units; majors (every 25) longer + heavier;
// labels at 0/50/100.
export const TICKS: DialTick[] = Array.from({ length: 21 }, (_, k) => k * 5).map((i) => {
  const t = i / 100;
  const major = i % 25 === 0;
  const [x1, y1] = pt(t, DIAL_CENTER.r + 2);
  const [x2, y2] = pt(t, DIAL_CENTER.r + (major ? 11 : 6));
  const label = i % 50 === 0 ? pt(t, DIAL_CENTER.r + 22) : null;
  return { i, major, x1, y1, x2, y2, label };
});

// Optional "recent normal" band in score units (0-100), clamped into the
// dial's [0,1] sweep fraction. Returns null when the band is missing,
// non-finite, or degenerate — including degenerate *after* clamping, e.g. a
// band that collapses to a single point once clamped into the sweep.
export function bandArc(baselineBand: [number, number] | undefined, r: number): string | null {
  if (!baselineBand || !Number.isFinite(baselineBand[0]) || !Number.isFinite(baselineBand[1])) {
    return null;
  }
  const lo = Math.max(0, Math.min(1, baselineBand[0] / 100));
  const hi = Math.max(0, Math.min(1, baselineBand[1] / 100));
  return hi > lo ? arcPath(lo, hi, r) : null;
}
