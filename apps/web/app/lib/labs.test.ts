import { describe, expect, test } from "bun:test";

import type { LabAssessment, LabGap, LabResult } from "./api";
import {
  BAND_LABEL,
  bandTone,
  changeSentence,
  gapSentence,
  historySentence,
  labChartGeometry,
  labRange,
  labValue,
  streakSentence,
} from "./labs";

const NORTH = "north";
const HARBOR = "harbor";

function result(over: Partial<LabResult>): LabResult {
  return {
    id: over.id ?? `${over.stream_id ?? NORTH}-${over.specimen_at ?? "2026-01-01T00:00:00Z"}`,
    specimen_at: "2026-01-01T00:00:00Z",
    date_only: true,
    value: 40,
    comparator: null,
    unit: "ng/mL",
    display_unit: "ng/mL",
    reference_low: 30,
    reference_high: 400,
    lab: "Northfield Diagnostics",
    stream_id: NORTH,
    source_plugin_id: "labs-csv",
    panel: null,
    quality_flags: [],
    band: "within",
    band_fraction: 0.03,
    ...over,
  };
}

function assessment(over: Partial<LabAssessment>): LabAssessment {
  return {
    latest_band: "within",
    previous_specimen_at: "2026-09-08T05:50:00Z",
    previous_from_other_lab: false,
    change: -5,
    change_pct: -20.83,
    direction: "down",
    change_withheld: null,
    prior_count: 3,
    prior_min: 24,
    prior_max: 64,
    versus_history: "below_prior_range",
    outside_streak: 0,
    ...over,
  };
}

describe("labs copy", () => {
  test("values keep their comparator and display unit", () => {
    expect(labValue(result({ value: 0.5, comparator: "<", display_unit: "mg/L" }))).toBe("<0.5 mg/L");
    expect(labValue(result({ value: 12.8, display_unit: "g/dL" }))).toBe("12.8 g/dL");
  });

  test("ranges are the lab's own, one-sided when the lab printed one side", () => {
    expect(labRange(result({}))).toBe("30–400 ng/mL");
    expect(labRange(result({ reference_low: null, reference_high: 5, display_unit: "mg/L" }))).toBe(
      "up to 5 mg/L",
    );
    expect(labRange(result({ reference_low: null, reference_high: null }))).toBe("no range printed");
  });

  test("band words never diagnose", () => {
    const words = Object.values(BAND_LABEL).join(" ").toLowerCase();
    for (const banned of ["abnormal", "deficien", "disease", "risk", "healthy", "normal"]) {
      expect(words.includes(banned)).toBe(false);
    }
    expect(bandTone("below")).toBe("out");
    expect(bandTone("within")).toBe("ok");
    expect(bandTone("no_range")).toBe("none");
  });

  test("change sentence names the other lab and withheld reasons", () => {
    expect(changeSentence(assessment({ previous_from_other_lab: true }), "ng/mL")).toBe(
      "Down 5 ng/mL (−20.83%) since Sep 8, 2026; the earlier result is from another lab.",
    );
    expect(changeSentence(assessment({ change: null, direction: null, change_withheld: "first result" }), "ng/mL")).toBe(
      "First result for this marker.",
    );
    expect(
      changeSentence(
        assessment({ change: null, direction: null, change_withheld: "the two results use different units" }),
        "ng/mL",
      ),
    ).toBe("No change shown: the two results use different units.");
  });

  test("history and streak sentences", () => {
    expect(historySentence(assessment({}), "ng/mL")).toBe("Lower than every earlier result (24–64 ng/mL).");
    expect(historySentence(assessment({ versus_history: null }), "ng/mL")).toBeNull();
    expect(streakSentence(assessment({ outside_streak: 3 }))).toBe("Outside the lab's range on the last 3 results.");
    expect(streakSentence(assessment({ outside_streak: 1 }))).toBeNull();
  });

  test("gap sentence states the difference, never a mean", () => {
    const gap: LabGap = {
      earlier_id: "a",
      later_id: "b",
      earlier_lab: "Northfield Diagnostics",
      later_lab: "Harbor Clinical Lab",
      earlier_specimen_at: "2026-09-08T05:50:00Z",
      later_specimen_at: "2026-09-17T00:00:00Z",
      earlier_value: 24,
      later_value: 19,
      unit: "ng/mL",
      days_apart: 8.76,
      difference: -5,
      difference_pct: -20.83,
      earlier_band: "below",
      later_band: "within",
      bands_disagree: true,
    };
    const sentence = gapSentence(gap, "ng/mL");
    expect(sentence).toBe("9 days apart, 5 ng/mL apart (−20.83%).");
    expect(sentence.toLowerCase().includes("average")).toBe(false);
  });
});

describe("lab chart geometry", () => {
  const results = [
    result({ specimen_at: "2025-11-18T00:00:00Z", value: 64 }),
    result({ specimen_at: "2026-03-10T07:15:00Z", value: 41 }),
    result({ specimen_at: "2026-09-08T05:50:00Z", value: 24, band: "below" }),
    result({
      specimen_at: "2026-09-17T00:00:00Z",
      value: 19,
      stream_id: HARBOR,
      lab: "Harbor Clinical Lab",
      reference_low: 15,
      reference_high: 300,
    }),
  ];

  test("each result gets its own band; a different lab's range shows as a step", () => {
    const geometry = labChartGeometry(results, [HARBOR, NORTH])!;
    expect(geometry.bands).toHaveLength(4);
    const north = geometry.bands[2];
    const harbor = geometry.bands[3];
    expect(harbor.y1).toBeGreaterThan(north.y1); // Harbor's low bound (15) sits lower than 30
    expect(harbor.x0).toBeCloseTo(north.x1, 5); // bands meet halfway between the two draws
  });

  test("lines join results of the same lab only", () => {
    const geometry = labChartGeometry(results, [HARBOR, NORTH])!;
    expect(geometry.lines).toHaveLength(1); // Northfield's three draws; Harbor's single draw has no line
    expect(geometry.points.map((p) => p.series)).toEqual([1, 1, 1, 0]);
  });

  test("the domain follows the values; near bounds join it, far bounds are clipped", () => {
    const geometry = labChartGeometry(results, [NORTH, HARBOR])!;
    expect(geometry.min).toBeLessThan(15); // the low bounds (15, 30) sit near the values
    expect(geometry.max).toBeLessThan(300); // 300 and 400 are far: clipped, not plotted
    expect(geometry.bands.every((band) => band.bottomEdge && !band.topEdge)).toBe(true);
    for (const point of geometry.points) {
      expect(point.y).toBeGreaterThanOrEqual(0);
      expect(point.y).toBeLessThanOrEqual(100);
    }
    for (const band of geometry.bands) {
      expect(band.y0).toBeGreaterThanOrEqual(0); // clipped at the chart edge
    }
  });

  test("no results, no chart", () => {
    expect(labChartGeometry([], [])).toBeNull();
  });
});

test("chart excludes limits and incompatible or unverified units without joining across the gap", () => {
  const a = result({ value: 10, specimen_at: "2026-01-01" });
  const limit = result({ value: 20, comparator: "<", specimen_at: "2026-02-01" });
  const b = result({ value: 30, specimen_at: "2026-03-01" });
  const geometry = labChartGeometry([a, limit, b], [NORTH])!;
  expect(geometry.points).toHaveLength(2);
  expect(geometry.lines).toHaveLength(0);
  expect(geometry.omitted).toBe(1);
  expect(labChartGeometry([a, result({ unit: "mg/L", specimen_at: "2026-04-01" })], [NORTH])!.points).toHaveLength(1);
  expect(labChartGeometry([result({ quality_flags: ["unit_unreconciled"] })], [NORTH])).toBeNull();
  expect(labChartGeometry([limit], [NORTH])).toBeNull();
});
