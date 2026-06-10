import { describe, expect, it } from "bun:test";

// Smoke tests over the real view-logic chain the Observatory pages run:
// series -> analytics pivots (Patterns), per-stream split + opinion layer
// (Compare), provenance -> coverage -> verdict (Sources), and the privacy
// posture chip (Shell). Pure logic over the deterministic demo fixtures the
// pages themselves fall back to — if any link in these flows reshapes, the
// page renders empty or wrong and these go red before a deploy does.

import {
  bucketBy,
  classify,
  dayOfWeekPivot,
  distribution,
  groupBySource,
  groupByStream,
  hrZoneHistogram,
  periodSplit,
  weekHourPivot,
} from "./analytics";
import { DEMO_COMPARE_SERIES, demoPatternSeries } from "./demoSeries";
import { comparability, coverageVerdict } from "./healthOpinion";
import { buildCoverage, DEMO_PROVENANCE } from "./provenance";
import { postureChip } from "./load";

const HEART_RATE = {
  id: "heart_rate",
  display_name: "Heart Rate",
  category: "cardio",
  value_type: "quantity",
  canonical_unit: "bpm",
};

describe("Patterns flow: demo series through every pivot", () => {
  const series = demoPatternSeries(HEART_RATE);

  it("demo series feeds the heatmap, weekday, zone, and table panels", () => {
    expect(series.points.length).toBeGreaterThan(0);

    const heat = weekHourPivot(series.points);
    expect(heat.some((c) => c.n > 0)).toBe(true);

    const dows = dayOfWeekPivot(series.points);
    expect(dows.filter((d) => d.n > 0).length).toBe(7);

    const zones = hrZoneHistogram(series.points);
    expect(zones.reduce((sum, z) => sum + z.count, 0)).toBe(series.points.length);

    const daily = bucketBy(series.points, "day", "mean");
    expect(daily.length).toBe(14);
  });

  it("source panels split without losing points", () => {
    const bySource = groupBySource(series.points);
    expect([...bySource.keys()].sort()).toEqual(["Apple Watch", "Whoop"]);
    const total = [...bySource.values()].reduce((sum, pts) => sum + pts.length, 0);
    expect(total).toBe(series.points.length);
    expect(distribution(series.points).length).toBe(2);
  });

  it("period split and threshold classification stay sane", () => {
    const split = periodSplit(series.points);
    expect(split.a.n + split.b.n).toBe(series.points.length);
    expect(["up", "down", "flat"]).toContain(split.delta.direction);

    const band = classify("vital.resting_heart_rate", 60);
    expect(band?.label).toBe("typical");
    // Unknown metrics get no band — the opinion layer must never invent one.
    expect(classify("heart_rate", 60)).toBeNull();
  });
});

describe("Compare flow: cross-vendor HRV is shown, warned, never merged", () => {
  it("demo compare series keeps both streams verbatim", () => {
    const byStream = groupByStream(DEMO_COMPARE_SERIES.points);
    expect(byStream.size).toBe(2);
    for (const pts of byStream.values()) {
      expect(pts.every((p) => typeof p.value === "number")).toBe(true);
    }
  });

  it("opinion layer flags Apple-SDNN vs Whoop-RMSSD as not comparable", () => {
    const sources = [...groupBySource(DEMO_COMPARE_SERIES.points).keys()];
    const verdict = comparability("hrv_sdnn", sources);
    expect(verdict.comparable).toBe(false);
    expect(verdict.warn).toBe(true);
    expect(verdict.caveat).toContain("SDNN");
  });

  it("same-vendor comparisons pass without a warning", () => {
    const verdict = comparability("heart_rate", ["Apple Watch", "iPhone"]);
    expect(verdict.comparable).toBe(true);
    expect(verdict.warn).toBe(false);
  });
});

describe("Sources flow: provenance -> coverage -> verdict", () => {
  it("demo provenance builds an honest coverage summary", () => {
    const coverage = buildCoverage(DEMO_PROVENANCE);
    expect(coverage.total).toBe(DEMO_PROVENANCE.length);
    expect(coverage.headline).toBeGreaterThan(0);
    expect(coverage.headline).toBeLessThanOrEqual(100);
    expect(coverage.domains.length).toBeGreaterThan(0);
    expect(coverage.domains.length).toBeLessThanOrEqual(6);
  });

  it("coverage verdict takes a stance for every coverage state", () => {
    expect(coverageVerdict([]).state).toBe("caution");
    const allFresh = buildCoverage(DEMO_PROVENANCE).domains.map((d) => ({ ...d, tone: "ok" as const }));
    expect(coverageVerdict(allFresh).state).toBe("steady");
    const allStale = allFresh.map((d) => ({ ...d, tone: "warn" as const }));
    expect(coverageVerdict(allStale).state).toBe("suppressed");
  });
});

describe("Shell flow: privacy posture chip", () => {
  it("asserts nothing it cannot verify when the backend is down", () => {
    expect(postureChip(null)).toEqual({ text: "on-host", ok: true });
  });

  it("labels a disabled narrator as no-egress, an active cloud one as not-ok", () => {
    const base = { is_local: false, cloud_active: false, provider: "disabled" };
    expect(postureChip({ ...base } as never).ok).toBe(true);
    const cloud = { is_local: false, cloud_active: true, provider: "deepseek" };
    expect(postureChip(cloud as never)).toEqual({ text: "cloud · deepseek", ok: false });
  });
});
