import { describe, expect, it } from "bun:test";

import { dateDomainMs, dateTicks, declutterLabels, valueTicks } from "./axis";

describe("valueTicks", () => {
  it("places round ticks with fractional positions inside the domain", () => {
    const ticks = valueTicks(0, 100, 4);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(ticks[0].frac).toBeGreaterThanOrEqual(0);
    expect(ticks[ticks.length - 1].frac).toBeLessThanOrEqual(1);
    // frac must track value linearly across [lo, hi]
    for (const t of ticks) expect(t.frac).toBeCloseTo(t.value / 100);
  });

  it("drops ticks that fall outside the domain", () => {
    const ticks = valueTicks(3, 7, 4);
    for (const t of ticks) {
      expect(t.value).toBeGreaterThanOrEqual(3);
      expect(t.value).toBeLessThanOrEqual(7);
    }
  });

  it("degrades on a zero-width domain without NaN", () => {
    const ticks = valueTicks(5, 5);
    for (const t of ticks) expect(Number.isFinite(t.frac)).toBe(true);
  });
});

describe("dateTicks", () => {
  it("labels months for long windows", () => {
    const start = Date.UTC(2025, 0, 1);
    const end = Date.UTC(2025, 11, 31);
    const ticks = dateTicks(start, end);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(ticks.length).toBeLessThanOrEqual(5);
    expect(ticks[0].frac).toBeCloseTo(0);
    // first tick is the first of a month, short month label
    expect(ticks[0].label).toBe("Jan");
    expect(ticks.every((t) => /^[A-Z][a-z]{2}$/.test(t.label))).toBe(true);
  });

  it("labels days for short windows", () => {
    const start = Date.UTC(2025, 5, 1);
    const end = Date.UTC(2025, 5, 8); // 7 days
    const ticks = dateTicks(start, end);
    expect(ticks.length).toBe(3);
    expect(ticks[0].frac).toBe(0);
    expect(ticks[ticks.length - 1].frac).toBe(1);
    // day + month form, e.g. "1 Jun"
    expect(ticks[0].label).toMatch(/\d+ [A-Z][a-z]{2}/);
  });

  it("returns nothing for an invalid or degenerate range", () => {
    expect(dateTicks(100, 100)).toEqual([]);
    expect(dateTicks(200, 100)).toEqual([]);
    expect(dateTicks(Number.NaN, 100)).toEqual([]);
  });

  it("keeps fractions monotonic and within [0,1]", () => {
    const start = Date.UTC(2024, 0, 1);
    const end = Date.UTC(2024, 8, 1);
    const ticks = dateTicks(start, end);
    for (const t of ticks) {
      expect(t.frac).toBeGreaterThanOrEqual(0);
      expect(t.frac).toBeLessThanOrEqual(1);
    }
    for (let i = 1; i < ticks.length; i++) {
      expect(ticks[i].frac).toBeGreaterThan(ticks[i - 1].frac);
    }
  });
});

describe("declutterLabels", () => {
  it("leaves already-separated labels untouched", () => {
    expect(declutterLabels([10, 40, 80], 14, 0, 100)).toEqual([10, 40, 80]);
  });
  it("pushes colliding labels apart to at least minGap, preserving order", () => {
    const out = declutterLabels([50, 52], 14, 0, 100);
    expect(out[1] - out[0]).toBeGreaterThanOrEqual(14 - 1e-9);
    // input order is preserved (first stays the lower position)
    expect(out[0]).toBeLessThan(out[1]);
  });
  it("shifts the block up when spreading would overflow the bottom bound", () => {
    const out = declutterLabels([95, 96, 97], 14, 0, 100);
    for (const v of out) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    }
    for (let i = 1; i < out.length; i++) {
      expect(out[i] - out[i - 1]).toBeGreaterThanOrEqual(14 - 1e-9);
    }
  });
  it("keeps results mapped to their original indices regardless of input order", () => {
    // higher desired position first — output must still line up index-for-index
    const out = declutterLabels([80, 10], 14, 0, 100);
    expect(out[0]).toBeGreaterThan(out[1]);
  });
  it("clamps a single label and handles the empty case", () => {
    expect(declutterLabels([120], 14, 0, 100)).toEqual([100]);
    expect(declutterLabels([], 14, 0, 100)).toEqual([]);
  });
});

describe("dateDomainMs", () => {
  it("parses a valid ISO pair", () => {
    const ms = dateDomainMs(["2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z"]);
    expect(ms).not.toBeNull();
    expect((ms as [number, number])[1]).toBeGreaterThan((ms as [number, number])[0]);
  });

  it("rejects missing, unparseable, or inverted pairs", () => {
    expect(dateDomainMs(undefined)).toBeNull();
    expect(dateDomainMs(["nope", "2025-02-01"])).toBeNull();
    expect(dateDomainMs(["2025-02-01", "2025-01-01"])).toBeNull();
  });
});
