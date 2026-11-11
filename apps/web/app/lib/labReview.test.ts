import { expect, test } from "bun:test";
import { newReviewRow, reportSpecimenDate } from "./labReview";

test("manual rows work on LAN HTTP without secure-context randomUUID", () => {
  const descriptor = Object.getOwnPropertyDescriptor(crypto, "randomUUID");
  Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
  try {
    const one = newReviewRow(); const two = newReviewRow();
    expect(one.row_id).toMatch(/^manual-[a-f0-9]{32}$/);
    expect(two.row_id).not.toBe(one.row_id);
    expect(one.confirmed).toBe(false);
  } finally {
    if (descriptor) Object.defineProperty(crypto, "randomUUID", descriptor);
    else delete (crypto as unknown as Record<string, unknown>).randomUUID;
  }
});

test("sample timestamps disclose UTC while date-only reports keep their calendar date", () => {
  expect(reportSpecimenDate("2026-01-02T00:30:00+03:00", [])).toBe("2026-01-01 21:30:00 UTC");
  expect(reportSpecimenDate("2026-01-02T00:00:00Z", ["date_only"])).toBe("2026-01-02");
});
