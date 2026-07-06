import { describe, expect, it } from "bun:test";

import { A0, A1, arcPath, bandArc, R_ARC, TICKS } from "./dialGeometry";

describe("arcPath", () => {
  it("uses the small-arc flag for spans under 180 degrees of sweep", () => {
    // 240deg total sweep; a fraction span just under 0.75 stays under 180deg.
    const d = arcPath(0, 0.74, R_ARC);
    expect(d).toMatch(/A \d+ \d+ 0 0 1 /);
  });

  it("flips to the large-arc flag exactly at the 180deg boundary", () => {
    // abs(t1 - t0) * 240 > 180  <=>  span > 0.75; at exactly 0.75 the flag is
    // still 0 (strict '>' in the source), then 1 just past it.
    const atBoundary = arcPath(0, 0.75, R_ARC);
    expect(atBoundary).toMatch(/A \d+ \d+ 0 0 1 /);

    const pastBoundary = arcPath(0, 0.750001, R_ARC);
    expect(pastBoundary).toMatch(/A \d+ \d+ 0 1 1 /);
  });

  it("always uses sweep-flag 1", () => {
    expect(arcPath(0, 1, R_ARC)).toMatch(/A \d+ \d+ 0 [01] 1 /);
    expect(arcPath(1, 0, R_ARC)).toMatch(/A \d+ \d+ 0 [01] 1 /);
  });

  it("starts and ends on the sweep's start/end angles", () => {
    const d = arcPath(0, 1, R_ARC);
    const match = d.match(/^M (-?[\d.]+) (-?[\d.]+) A/);
    expect(match).not.toBeNull();
    // t=0 sits at the A0 angle: cos/sin of A0 in degrees, centered on DIAL_CENTER.
    const rad = (A0 * Math.PI) / 180;
    const expectedX = 130 + Math.cos(rad) * R_ARC;
    const expectedY = 128 - Math.sin(rad) * R_ARC;
    expect(Number(match![1])).toBeCloseTo(expectedX, 1);
    expect(Number(match![2])).toBeCloseTo(expectedY, 1);
    expect(A1).toBe(-30); // sanity: 240deg sweep from 210 to -30
  });
});

describe("bandArc", () => {
  it("clamps an out-of-range band into the [0,1] sweep", () => {
    const clamped = bandArc([-10, 120], R_ARC);
    const full = arcPath(0, 1, R_ARC);
    expect(clamped).toBe(full);
  });

  it("returns null for a degenerate band that collapses after clamping", () => {
    // Both endpoints clamp to 0, so lo === hi post-clamp -> no visible band.
    expect(bandArc([-10, 0], R_ARC)).toBeNull();
    // Both endpoints clamp to 1.
    expect(bandArc([100, 500], R_ARC)).toBeNull();
  });

  it("returns null when the band is missing or non-finite", () => {
    expect(bandArc(undefined, R_ARC)).toBeNull();
    expect(bandArc([Number.NaN, 50], R_ARC)).toBeNull();
    expect(bandArc([10, Number.POSITIVE_INFINITY], R_ARC)).toBeNull();
  });

  it("returns null when hi <= lo within range", () => {
    expect(bandArc([50, 50], R_ARC)).toBeNull();
    expect(bandArc([60, 40], R_ARC)).toBeNull();
  });

  it("draws a normal in-range band", () => {
    const d = bandArc([30, 70], R_ARC);
    expect(d).toBe(arcPath(0.3, 0.7, R_ARC));
  });
});

describe("TICKS", () => {
  it("generates a tick every 5 units from 0 to 100", () => {
    expect(TICKS.length).toBe(21);
    expect(TICKS[0].i).toBe(0);
    expect(TICKS[TICKS.length - 1].i).toBe(100);
    for (let k = 1; k < TICKS.length; k++) {
      expect(TICKS[k].i - TICKS[k - 1].i).toBe(5);
    }
  });

  it("marks majors every 25 units", () => {
    const majors = TICKS.filter((t) => t.major).map((t) => t.i);
    expect(majors).toEqual([0, 25, 50, 75, 100]);
  });

  it("labels only 0, 50, and 100", () => {
    const labeled = TICKS.filter((t) => t.label !== null).map((t) => t.i);
    expect(labeled).toEqual([0, 50, 100]);
  });
});
