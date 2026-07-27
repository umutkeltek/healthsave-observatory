import { describe, expect, test } from "bun:test";

import type { Finding, FindingCard } from "./api";
import {
  cardMetricIsPlottable,
  confidenceTone,
  displayItemsForFindings,
  effectSizeText,
  findingCardChips,
  groupFindingsForDisplay,
  recoveryEvidence,
  userFindingTitle,
} from "./findingPresentation";

const card = (overrides: Partial<FindingCard> = {}): FindingCard => ({
  schema_version: 1,
  claim: overrides.claim ?? "resting heart rate ran +5.8% vs your 30-day baseline",
  metric: overrides.metric ?? "vital.resting_heart_rate",
  finding_type: overrides.finding_type ?? "summary",
  current_window: overrides.current_window ?? null,
  baseline_window: overrides.baseline_window ?? null,
  delta: overrides.delta ?? null,
  effect_size: overrides.effect_size ?? null,
  coverage: overrides.coverage ?? null,
  sources: overrides.sources ?? [],
  confidence: overrides.confidence ?? null,
  limitations: overrides.limitations ?? [],
  confounders: overrides.confounders ?? [],
  next_question: overrides.next_question ?? null,
});

const finding = (overrides: Partial<Finding>): Finding => ({
  id: overrides.id ?? 1,
  finding_type: overrides.finding_type ?? "summary",
  metric: overrides.metric ?? "vital.hrv_sdnn",
  severity: overrides.severity ?? null,
  structured_data: overrides.structured_data ?? {},
  created_at: overrides.created_at ?? "2026-07-03T10:00:00Z",
  card: overrides.card ?? null,
  schema_version: overrides.schema_version ?? 0,
});

describe("finding presentation", () => {
  test("groups actionable items ahead of background evidence", () => {
    const grouped = groupFindingsForDisplay([
      finding({ id: 1, finding_type: "summary", metric: "vital.resting_heart_rate" }),
      finding({ id: 2, finding_type: "anomaly", metric: "vital.hrv_sdnn", severity: "warning" }),
      finding({ id: 3, finding_type: "trend", metric: "activity.steps", structured_data: { direction: "up" } }),
      finding({ id: 4, finding_type: "recovery_score", metric: "recovery" }),
    ]);

    expect(grouped.map((group) => group.id)).toEqual([
      "needs-attention",
      "improving",
      "watching",
      "background",
    ]);
    expect(grouped[0].findings.map((item) => item.id)).toEqual([2]);
    expect(grouped[1].findings.map((item) => item.id)).toEqual([3, 4]);
    expect(grouped[3].findings.map((item) => item.id)).toEqual([1]);
  });

  test("turns engine metric ids into readable titles", () => {
    expect(userFindingTitle(finding({ metric: "vital.hrv_sdnn" }))).toBe("Heart rate variability");
    expect(userFindingTitle(finding({ metric: "activity.steps" }))).toBe("Steps");
    expect(userFindingTitle(finding({ metric: "custom.metric_name" }))).toBe("Metric Name");
  });

  test("accepts only evidence-qualified recovery findings for the hero", () => {
    expect(
      recoveryEvidence(
        finding({
          finding_type: "recovery_score",
          structured_data: {
            score: 68,
            formula_version: 2,
            input_count: 3,
            input_total: 5,
            evidence_level: "partial",
          },
        }),
      ),
    ).toEqual({ score: 68, inputCount: 3, inputTotal: 5, evidenceLevel: "partial" });

    expect(
      recoveryEvidence(
        finding({
          finding_type: "recovery_score",
          structured_data: { score: 91, signals_available: ["hrv"] },
        }),
      ),
    ).toBeNull();

    expect(
      recoveryEvidence(
        finding({
          finding_type: "recovery_score",
          structured_data: {
            score: 140,
            formula_version: 2,
            input_count: 3,
            input_total: 5,
            evidence_level: "partial",
          },
        }),
      ),
    ).toBeNull();
  });

  test("clusters repeated recovery checks into one display item", () => {
    const items = displayItemsForFindings(
      [64, 67, 56, 70, 63].map((score, index) =>
        finding({
          id: index + 1,
          finding_type: "recovery_score",
          metric: "recovery",
          structured_data: { score },
          created_at: `2026-07-0${index + 1}T10:00:00Z`,
        }),
      ),
    );

    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe("cluster");
    expect(items[0].count).toBe(5);
    expect(items[0].key).toBe("cluster-recovery-score");
  });
});

describe("finding card presentation", () => {
  test("labels effect size by its statistical method", () => {
    expect(effectSizeText({ value: 2.14, kind: "z_score", label: "small", p_value: null })).toBe(
      "z = 2.14",
    );
    expect(
      effectSizeText({ value: 0.618, kind: "spearman_rho", label: "moderate", p_value: 0.02 }),
    ).toBe("ρ = 0.62");
    expect(
      effectSizeText({ value: 0.34, kind: "slope_per_day", label: null, p_value: null }),
    ).toBe("slope 0.34/day");
    expect(effectSizeText({ value: null, kind: "z_score", label: null, p_value: null })).toBeNull();
  });

  test("maps confidence onto a calm quality tone (never a verdict color)", () => {
    expect(confidenceTone("high")).toBe("good");
    expect(confidenceTone("medium")).toBe("neutral");
    expect(confidenceTone("low")).toBe("muted");
    expect(confidenceTone(null)).toBe("muted");
  });

  test("builds chips only from the fields a card actually carries", () => {
    const chips = findingCardChips(
      card({
        delta: { absolute: null, pct: 5.8, unit: null, direction: "up" },
        effect_size: { value: 2.1, kind: "z_score", label: "small", p_value: 0.008 },
        current_window: { label: "last 14 days", start: null, end: null, n: 14 },
        coverage: {
          is_sufficient: true,
          observation_count: 42,
          days_with_data: null,
          days_until_sufficient: null,
          note: null,
        },
        confidence: "high",
      }),
    );
    const byKey = Object.fromEntries(chips.map((c) => [c.key, c]));
    expect(byKey.delta.value).toBe("↑ +5.8%");
    expect(byKey.effect.value).toBe("z = 2.1");
    expect(byKey.effect.label).toBe("small effect");
    expect(byKey.p.value).toBe("p = 0.008");
    expect(byKey.n.value).toBe("n = 14");
    expect(byKey.coverage.value).toBe("42 obs");
    expect(byKey.coverage.tone).toBe("good");
    expect(byKey.confidence.tone).toBe("good");
  });

  test("a thin card renders no chips rather than fabricating them", () => {
    expect(findingCardChips(card())).toEqual([]);
  });

  test("renders an absolute-only delta (no pct) with its unit and sign", () => {
    const down = Object.fromEntries(
      findingCardChips(
        card({ delta: { absolute: -0.42, pct: null, unit: "kg", direction: "down" } }),
      ).map((c) => [c.key, c]),
    );
    expect(down.delta.value).toBe("↓ -0.42 kg");

    const up = Object.fromEntries(
      findingCardChips(
        card({ delta: { absolute: 1.5, pct: null, unit: null, direction: null } }),
      ).map((c) => [c.key, c]),
    );
    expect(up.delta.value).toBe("+1.5");
  });

  test("flags an insufficient-coverage card with a caution tone", () => {
    const chips = findingCardChips(
      card({
        coverage: {
          is_sufficient: false,
          observation_count: null,
          days_with_data: null,
          days_until_sufficient: 3,
          note: null,
        },
      }),
    );
    expect(chips[0]).toMatchObject({ key: "coverage", value: "thin", tone: "warn" });
  });

  test("a correlation-pair metric is not plottable as one series", () => {
    expect(cardMetricIsPlottable("vital.hrv_sdnn")).toBe(true);
    expect(cardMetricIsPlottable("vital.hrv_sdnn~vital.resting_heart_rate")).toBe(false);
    expect(cardMetricIsPlottable("")).toBe(false);
  });
});
