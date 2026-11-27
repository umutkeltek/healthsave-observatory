import { describe, expect, test } from "bun:test";

import { experimentStatus, isRunning, pairKey, runningPairKeys } from "./experimentStatus";

const exp = (status: string, lever = "activity.steps", outcome = "vital.hrv_sdnn") => ({
  status,
  lever_metric_id: lever,
  outcome_metric_id: outcome,
});

describe("experiment status", () => {
  test("only the three server statuses are recognised; anything else is unknown", () => {
    expect(experimentStatus("collecting")).toBe("collecting");
    expect(experimentStatus("completed")).toBe("completed");
    expect(experimentStatus("abandoned")).toBe("abandoned");
    expect(experimentStatus("COLLECTING")).toBe("unknown");
    expect(experimentStatus("")).toBe("unknown");
  });

  test("only a collecting experiment is running", () => {
    expect(isRunning("collecting")).toBe(true);
    for (const status of ["completed", "abandoned", "paused", ""]) expect(isRunning(status)).toBe(false);
  });

  // The bug: the "already running" set was every experiment that was not
  // abandoned, so a finished experiment blocked starting the same pair again.
  test("a completed experiment does not block restarting its pair", () => {
    const keys = runningPairKeys([exp("completed"), exp("abandoned")]);
    expect(keys.size).toBe(0);
  });

  test("a collecting experiment does", () => {
    const keys = runningPairKeys([exp("collecting"), exp("completed", "a.b", "c.d")]);
    expect([...keys]).toEqual([pairKey("vital.hrv_sdnn", "activity.steps")]);
  });
});
