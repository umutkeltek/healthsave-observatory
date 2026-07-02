import { describe, expect, test } from "bun:test";

import { anomalyPinIndices, findingMetricToOntology } from "./annotations";
import type { Finding } from "./api";

const anomaly = (metric: string, detectedAt: string, type = "anomaly"): Finding => ({
  id: 1,
  finding_type: type,
  metric,
  severity: "warning",
  structured_data: { detected_at: detectedAt, magnitude: -2.3 },
  created_at: detectedAt,
});

const DAYS = ["2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z", "2026-06-03T00:00:00Z"];

describe("findingMetricToOntology", () => {
  test("maps engine names to ontology ids", () => {
    expect(findingMetricToOntology("hrv")).toBe("vital.hrv_sdnn");
    expect(findingMetricToOntology("heart_rate")).toBe("vital.heart_rate");
  });
  test("passes ontology ids through and rejects unknowns", () => {
    expect(findingMetricToOntology("vital.spo2")).toBe("vital.spo2");
    expect(findingMetricToOntology("mystery")).toBeNull();
    expect(findingMetricToOntology(null)).toBeNull();
  });
});

describe("anomalyPinIndices", () => {
  test("pins an anomaly to the nearest point", () => {
    const pins = anomalyPinIndices(
      DAYS,
      [anomaly("hrv", "2026-06-02T05:00:00Z")],
      "vital.hrv_sdnn",
    );
    expect(pins).toEqual([1]);
  });

  test("ignores findings for other metrics and other types", () => {
    const findings = [
      anomaly("heart_rate", "2026-06-02T00:00:00Z"),
      anomaly("hrv", "2026-06-02T00:00:00Z", "trend"),
    ];
    expect(anomalyPinIndices(DAYS, findings, "vital.hrv_sdnn")).toEqual([]);
  });

  test("drops anomalies outside the tolerance window (out-of-range never pins to an edge)", () => {
    const pins = anomalyPinIndices(
      DAYS,
      [anomaly("hrv", "2026-05-20T00:00:00Z")],
      "vital.hrv_sdnn",
    );
    expect(pins).toEqual([]);
  });

  test("dedupes two anomalies landing on the same point and sorts indices", () => {
    const findings = [
      anomaly("hrv", "2026-06-03T01:00:00Z"),
      anomaly("hrv", "2026-06-02T23:00:00Z"),
      anomaly("hrv", "2026-06-01T02:00:00Z"),
    ];
    expect(anomalyPinIndices(DAYS, findings, "vital.hrv_sdnn")).toEqual([0, 2]);
  });

  test("handles empty inputs and malformed dates", () => {
    expect(anomalyPinIndices([], [anomaly("hrv", DAYS[0])], "vital.hrv_sdnn")).toEqual([]);
    expect(anomalyPinIndices(DAYS, null, "vital.hrv_sdnn")).toEqual([]);
    expect(
      anomalyPinIndices(DAYS, [anomaly("hrv", "not-a-date")], "vital.hrv_sdnn"),
    ).toEqual([]);
  });
});
