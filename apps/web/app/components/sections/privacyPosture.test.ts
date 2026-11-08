// A privacy read that failed must not render as the green "stays local" posture.
import { describe, expect, test } from "bun:test";

import type { Privacy } from "../../lib/api";
import { postureChip } from "../../lib/load";
import { vaultReceipt } from "./TodaySections";

const LOCAL = { provider: "ollama", is_local: true, cloud_active: false } as Privacy;

describe("privacy posture when the read failed", () => {
  test("the shell chip says unknown and does not claim the safe state", () => {
    expect(postureChip(null)).toEqual({ text: "posture unknown", ok: false });
  });

  test("the Today vault says unknown instead of 'Stays local · Cloud sharing off'", () => {
    const receipt = vaultReceipt(null, null);
    expect(receipt.variant).toBe("unknown");
    expect(receipt.seal).toBe("Privacy status unknown");
    const cloud = receipt.steps.find((step) => step.label === "Cloud sharing");
    expect(cloud?.meta).toBe("unknown");
    expect(cloud?.blocked).toBeFalsy();
    expect(receipt.steps.map((step) => step.meta)).not.toContain("local");
  });

  test("a read that answered keeps today's local posture", () => {
    const receipt = vaultReceipt(LOCAL, null);
    expect(receipt.variant).toBe("local");
    expect(receipt.seal).toBe("Stays local");
    expect(receipt.steps.find((step) => step.label === "Cloud sharing")).toEqual({
      label: "Cloud sharing",
      meta: "off",
      blocked: true,
    });
    expect(postureChip(LOCAL).ok).toBe(true);
  });
});
