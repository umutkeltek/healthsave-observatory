import { describe, expect, test } from "bun:test";

import type { CardExperimentCandidate } from "./api";
import { experimentHref, parseExperimentPrefill } from "./experimentPrefill";

const candidate = (overrides: Partial<CardExperimentCandidate> = {}): CardExperimentCandidate => ({
  metric_a: overrides.metric_a ?? "sleep.duration",
  metric_b: overrides.metric_b ?? "vital.hrv_sdnn",
  verdict: overrides.verdict ?? "testable",
  lever: overrides.lever ?? "sleep.duration",
  outcome: overrides.outcome ?? "vital.hrv_sdnn",
  suggested_protocol: overrides.suggested_protocol ?? "8h in bed for 2 weeks, alternating blocks",
  required_days: overrides.required_days ?? 14,
});

describe("experiment prefill", () => {
  test("builds a read-only /experiments link from a card candidate", () => {
    const href = experimentHref(candidate());
    expect(href).not.toBeNull();
    const url = new URL(href as string, "https://x");
    expect(url.pathname).toBe("/experiments");
    expect(url.searchParams.get("lever")).toBe("sleep.duration");
    expect(url.searchParams.get("outcome")).toBe("vital.hrv_sdnn");
    expect(url.searchParams.get("days")).toBe("14");
  });

  test("returns null without both a lever and an outcome", () => {
    expect(experimentHref({ ...candidate(), lever: null })).toBeNull();
    expect(experimentHref({ ...candidate(), outcome: null })).toBeNull();
    expect(experimentHref(null)).toBeNull();
  });

  test("href round-trips back through the prefill parser", () => {
    const href = experimentHref(candidate()) as string;
    const query = Object.fromEntries(new URL(href, "https://x").searchParams.entries());
    const prefill = parseExperimentPrefill(query);
    expect(prefill).toEqual({
      lever: "sleep.duration",
      outcome: "vital.hrv_sdnn",
      protocol: "8h in bed for 2 weeks, alternating blocks",
      requiredDays: 14,
    });
  });

  test("rejects a params bag missing the pair", () => {
    expect(parseExperimentPrefill({})).toBeNull();
    expect(parseExperimentPrefill({ lever: "sleep.duration" })).toBeNull();
    expect(parseExperimentPrefill({ lever: " ", outcome: "x" })).toBeNull();
  });

  test("takes the first value of a repeated param and drops a non-positive day count", () => {
    const prefill = parseExperimentPrefill({
      lever: ["sleep.duration", "steps"],
      outcome: "vital.hrv_sdnn",
      days: "0",
    });
    expect(prefill?.lever).toBe("sleep.duration");
    expect(prefill?.requiredDays).toBeNull();
    expect(prefill?.protocol).toBeNull();
  });
});
