import { describe, expect, test } from "bun:test";

import type { Finding } from "./api";
import {
  displayItemsForFindings,
  groupFindingsForDisplay,
  userFindingTitle,
} from "./findingPresentation";

const finding = (overrides: Partial<Finding>): Finding => ({
  id: overrides.id ?? 1,
  finding_type: overrides.finding_type ?? "summary",
  metric: overrides.metric ?? "vital.hrv_sdnn",
  severity: overrides.severity ?? null,
  structured_data: overrides.structured_data ?? {},
  created_at: overrides.created_at ?? "2026-07-03T10:00:00Z",
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
