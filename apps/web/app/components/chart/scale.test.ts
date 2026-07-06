import { describe, expect, it } from "bun:test";

import { extent, linearScale, niceTicks, quantile, robustDomain } from "./scale";

describe("quantile", () => {
  it("interpolates between sorted values", () => {
    expect(quantile([0, 10], 0.5)).toBe(5);
    expect(quantile([1, 2, 3, 4], 0.25)).toBeCloseTo(1.75);
  });
  it("handles the endpoints", () => {
    expect(quantile([3, 7, 9], 0)).toBe(3);
    expect(quantile([3, 7, 9], 1)).toBe(9);
  });
  it("handles a single value", () => {
    expect(quantile([42], 0.75)).toBe(42);
  });
});

describe("extent", () => {
  it("finds min and max", () => {
    expect(extent([3, -1, 7, 2])).toEqual([-1, 7]);
  });
});

describe("linearScale", () => {
  it("maps domain to range", () => {
    const scale = linearScale([0, 100], [0, 1000]);
    expect(scale(50)).toBe(500);
  });
  it("supports inverted ranges (SVG y-axis)", () => {
    const scale = linearScale([0, 10], [100, 0]);
    expect(scale(0)).toBe(100);
    expect(scale(10)).toBe(0);
  });
  it("degrades on a zero-width domain instead of dividing by zero", () => {
    const scale = linearScale([5, 5], [0, 100]);
    expect(Number.isFinite(scale(5))).toBe(true);
  });
});

describe("niceTicks", () => {
  it("produces round-number ticks inside the domain", () => {
    const ticks = niceTicks(0, 100, 4);
    expect(ticks[0]).toBeGreaterThanOrEqual(0);
    expect(ticks[ticks.length - 1]).toBeLessThanOrEqual(100);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
  });
  it("handles a degenerate domain", () => {
    expect(niceTicks(5, 5)).toEqual([5]);
  });
  it("rounds the raw step UP so density never blows past the target", () => {
    // Regression: a span-18 range at count 4 gives raw step 4.5. Flooring it to
    // 2 produced ten cramped ticks (the live Resting-HR bug); rounding up to 5
    // yields four.
    const ticks = niceTicks(38, 56, 4);
    expect(ticks).toEqual([40, 45, 50, 55]);
    expect(ticks.length).toBeLessThanOrEqual(5);
  });
  it("never emits more than count + 1 ticks for any span", () => {
    for (const [min, max] of [
      [0, 100],
      [38, 56],
      [44, 56],
      [40, 54],
      [0.1, 0.9],
      [12.3, 98.7],
    ]) {
      expect(niceTicks(min, max, 4).length).toBeLessThanOrEqual(5);
    }
  });
});

describe("robustDomain", () => {
  it("clips outliers to the p2-p98 band so spikes don't flatten the trace", () => {
    // 300 values near 50 plus a few huge spikes (<1%); the domain must ignore them.
    const values = [...Array(300).keys()].map((i) => 50 + (i % 5));
    values.push(500, 800, 1200);
    const [min, max] = robustDomain(values);
    expect(max).toBeLessThan(100); // nowhere near the 1200 spike
    expect(min).toBeGreaterThanOrEqual(50);
  });
  it("always contains the baseline band bounds", () => {
    const [min, max] = robustDomain([48, 49, 50, 51, 52], 45, 60);
    expect(min).toBeLessThanOrEqual(45);
    expect(max).toBeGreaterThanOrEqual(60);
  });
  it("returns a positive-width domain for a constant series", () => {
    const [min, max] = robustDomain([7, 7, 7, 7]);
    expect(max).toBeGreaterThan(min);
    expect(min).toBeLessThanOrEqual(7);
    expect(max).toBeGreaterThanOrEqual(7);
  });
  it("degrades to a finite domain for an empty series", () => {
    expect(robustDomain([])).toEqual([0, 1]);
    // With only a band and no series, the band defines the domain.
    expect(robustDomain([], 10, 20)).toEqual([10, 20]);
  });
});
