import { describe, expect, test } from "bun:test";
import { BAND_LABEL, MIN_PLOT_W, crossesBox, placeBandLabels } from "./bandLabels";

// A plot 132px tall with the band from 60px to 80px, like Sleep's card.
const plot = { top: 60, bottom: 80, height: 132, high: "7h 32m", low: "7h 3m" };
const flat = (y: number, n = 30) => Array.from({ length: n }, (_, i) => [i / (n - 1), y] as const);

describe("band labels never sit on the line", () => {
  test("with the line inside the band, both labels sit outside it at the left", () => {
    expect(placeBandLabels({ ...plot, trace: flat(70) })).toEqual({
      high: { at: "left", side: "above" },
      low: { at: "left", side: "below" },
    });
  });

  test("a line climbing through the top-left label moves that label to the right end", () => {
    // Sleep at phone width: the first nights run up through "7h 32m".
    const trace = flat(70).map(([x, y]) => [x, x < 0.15 ? 48 : y] as const);
    const spots = placeBandLabels({ ...plot, trace });
    expect(spots.high).toEqual({ at: "right", side: "above" });
    // The pair stays together where it can.
    expect(spots.low).toEqual({ at: "right", side: "below" });
  });

  test("blocked above at both ends, the label goes inside the band", () => {
    const trace = flat(48);
    expect(placeBandLabels({ ...plot, bottom: 100, trace }).high).toEqual({
      at: "left",
      side: "below",
    });
  });

  test("blocked at both ends, a label tries points along the band", () => {
    const trace = flat(70).map(([x, y]) => [x, x < 0.2 || x > 0.8 ? 50 : y] as const);
    expect(placeBandLabels({ ...plot, trace }).high).toEqual({ at: 0.25, side: "above" });
  });

  test("with no clear spot a label is left out rather than drawn on the line", () => {
    // A zig-zag that sweeps every height on every day.
    const trace = Array.from({ length: 30 }, (_, i) => [i / 29, i % 2 ? 0 : 132] as const);
    expect(placeBandLabels({ ...plot, trace })).toEqual({ high: null, low: null });
  });

  test("a thin band never stacks both labels inside it", () => {
    const trace = flat(40).map(([x], i) => [x, i % 2 ? 40 : 100] as const);
    const spots = placeBandLabels({ ...plot, top: 66, bottom: 74, trace });
    // Inside would mean below the top edge or above the bottom edge.
    expect(spots.high?.side).not.toBe("below");
    expect(spots.low?.side).not.toBe("above");
  });

  test("the checked box contains the real label at any plot at least MIN_PLOT_W wide", () => {
    // At 240px "7h 32m" reaches 4 + 6 * 6.4 + 3 = 45.4px; on a 400px plot the
    // real label ends at 11%, inside the 19% that was checked.
    const reach = (BAND_LABEL.inset + 6 * BAND_LABEL.char + BAND_LABEL.halo) / MIN_PLOT_W;
    expect(reach).toBeGreaterThan(45.4 / 400);
    // A segment that only enters the label's area on the narrowest plot is
    // still treated as crossing.
    const box = { x0: 0, x1: reach, y0: 44, y1: 55 };
    expect(crossesBox([[0.18, 50], [0.3, 50]], box)).toBe(true);
    expect(crossesBox([[0.25, 50], [0.3, 50]], box)).toBe(false);
  });

  test("a lone reading between two gaps counts as part of the line", () => {
    const box = { x0: 0, x1: 0.2, y0: 44, y1: 55 };
    expect(crossesBox([null, [0.1, 50], null], box)).toBe(true);
    expect(crossesBox([null, [0.1, 90], null], box)).toBe(false);
  });
});
