import { expect, test } from "bun:test";
import { applyReviewDetails, editReviewRow, newReviewRow, pdfReviewExcerpt, reportSpecimenDate, REVIEW_DEFAULTS } from "./labReview";

test("changing any reviewed field requires confirmation again", () => {
  const row = { ...REVIEW_DEFAULTS, confirmed: true };
  for (const field of ["loinc", "marker_name", "value", "unit", "reference_low", "reference_high", "specimen_datetime", "lab", "panel"] as const) {
    expect(editReviewRow(row, field, "corrected").confirmed).toBe(false);
  }
  expect(editReviewRow(row, "confirmed", true).confirmed).toBe(true);
  expect(editReviewRow(row, "confirmed", false).confirmed).toBe(false);
});

test("shared details clear confirmations while preserving values not supplied", () => {
  const row = { ...REVIEW_DEFAULTS, specimen_datetime: "2026-01-02", lab: "Original lab", confirmed: true };
  expect(applyReviewDetails([row], "", "Updated lab")[0]).toEqual({ ...row, lab: "Updated lab", confirmed: false });
  expect(applyReviewDetails([row], "2026-02-03", "")[0]).toEqual({ ...row, specimen_datetime: "2026-02-03", confirmed: false });
});

test("source excerpt uses the exact page and line, never guesses CSV or manual rows", () => {
  const pages = [{ page: 2, text: "Header\r\nFerritin 12 ng/mL\nDifferent test", method: "text" as const }];
  expect(pdfReviewExcerpt("p2-l2", pages)).toBe("Ferritin 12 ng/mL");
  for (const id of ["p1-l2", "p2-l0", "p2-l99", "csv-2", "manual-123"]) {
    expect(pdfReviewExcerpt(id, pages)).toBeNull();
  }
});

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
