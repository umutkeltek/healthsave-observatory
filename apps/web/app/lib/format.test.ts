import { describe, expect, test } from "bun:test";

import { formatPValue, pValueLabel } from "./format";

describe("p-values", () => {
  test("three decimals while they fit", () => {
    expect(formatPValue(0.0071)).toBe("0.007");
    expect(formatPValue(0.05)).toBe("0.05");
    expect(pValueLabel(0.0071)).toBe("p = 0.007");
  });

  test("a p-value that rounds to zero reads as below 0.001, never as 0", () => {
    expect(formatPValue(0)).toBe("< 0.001");
    expect(formatPValue(1.2e-9)).toBe("< 0.001");
    expect(pValueLabel(0)).toBe("p < 0.001");
  });
});
