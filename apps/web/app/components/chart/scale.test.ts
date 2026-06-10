import { describe, expect, it } from "bun:test";

import { extent, linearScale, niceTicks, quantile } from "./scale";

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
});
