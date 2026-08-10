import { describe, expect, test } from "bun:test";

import { positiveIsGoodFor } from "./direction";

describe("positiveIsGoodFor", () => {
  test("returns false for lower-is-better vitals", () => {
    expect(positiveIsGoodFor("vital.resting_heart_rate")).toBe(false);
    expect(positiveIsGoodFor("vital.respiratory_rate")).toBe(false);
    expect(positiveIsGoodFor("vital.walking_heart_rate_average")).toBe(false);
    expect(positiveIsGoodFor("mobility.walking_asymmetry")).toBe(false);
  });

  test("returns true for higher-is-better signals", () => {
    expect(positiveIsGoodFor("vital.hrv_sdnn")).toBe(true);
    expect(positiveIsGoodFor("vital.blood_oxygen")).toBe(true);
    expect(positiveIsGoodFor("activity.steps")).toBe(true);
    expect(positiveIsGoodFor("mobility.walking_speed")).toBe(true);
  });

  test("derives direction from THRESHOLDS for metrics not in the explicit map", () => {
    // blood_oxygen is also in THRESHOLDS (top band "normal" → ok) → higher better.
    expect(positiveIsGoodFor("vital.blood_oxygen")).toBe(true);
  });

  test("returns null when direction is unknown so callers stay neutral", () => {
    expect(positiveIsGoodFor("custom.unknown_metric")).toBeNull();
  });
});
