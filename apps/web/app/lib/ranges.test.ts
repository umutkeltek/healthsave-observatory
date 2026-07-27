import { describe, expect, test } from "bun:test";
import type { SeriesPoint } from "./api";
import { hasUsablePoints, isRangeOption, rangeLabel, seriesCoverage } from "./ranges";

function point(t: string, value: number | null, code: string | null = null): SeriesPoint {
  return { t, value, code, unit: null, source_id: "test", stream_id: null, confidence: null };
}

describe("range utilities", () => {
  test("recognizes all shared range presets", () => {
    expect(isRangeOption("all")).toBe(true);
    expect(isRangeOption("24h")).toBe(true);
    expect(isRangeOption("5y")).toBe(false);
    expect(rangeLabel("all")).toBe("All time");
  });

  test("treats coded and numeric observations as usable", () => {
    const metric = { id: "sleep.stage", display_name: "Sleep", category: "sleep", value_type: "code", canonical_unit: null };
    expect(hasUsablePoints({ metric, range: "7d", start: "", end: "", points: [point("2026-01-01T00:00:00Z", null, "deep")] })).toBe(true);
  });

  test("reports actual chronological coverage independent of input order", () => {
    const coverage = seriesCoverage([
      point("2026-03-01T00:00:00Z", 3),
      point("2025-01-01T00:00:00Z", 1),
      point("2026-01-01T00:00:00Z", 2),
    ]);
    expect(coverage).toEqual({ first: "2025-01-01T00:00:00Z", last: "2026-03-01T00:00:00Z", count: 3 });
  });
});
