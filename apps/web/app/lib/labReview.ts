import type { ReviewRow } from "./labImportTypes";

export const REVIEW_DEFAULTS: ReviewRow = {
  row_id: "", specimen_datetime: "", loinc: "", marker_name: "", value: "", unit: "",
  reference_low: "", reference_high: "", lab: "", panel: "", confirmed: false,
};

export function newReviewRow(): ReviewRow {
  // getRandomValues also works on ordinary http:// LAN Observatory addresses.
  const random = Array.from(crypto.getRandomValues(new Uint32Array(4)), n => n.toString(16).padStart(8, "0")).join("");
  return { ...REVIEW_DEFAULTS, row_id: `manual-${random}` };
}

export function reportSpecimenDate(timestamp: string, flags: string[]): string {
  if (flags.includes("date_only")) return timestamp.slice(0, 10);
  return new Date(timestamp).toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
}
