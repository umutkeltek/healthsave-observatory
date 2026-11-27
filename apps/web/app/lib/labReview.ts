import type { LabImportDraft, ReviewRow } from "./labImportTypes";

export const REVIEW_DEFAULTS: ReviewRow = {
  row_id: "", specimen_datetime: "", loinc: "", marker_name: "", value: "", unit: "",
  reference_low: "", reference_high: "", lab: "", panel: "", confirmed: false,
};

export function newReviewRow(): ReviewRow {
  // getRandomValues also works on ordinary http:// LAN Observatory addresses.
  const random = Array.from(crypto.getRandomValues(new Uint32Array(4)), n => n.toString(16).padStart(8, "0")).join("");
  return { ...REVIEW_DEFAULTS, row_id: `manual-${random}` };
}

export function editReviewRow(row: ReviewRow, field: keyof ReviewRow, value: string | boolean): ReviewRow {
  return { ...row, [field]: value, ...(field === "confirmed" ? {} : { confirmed: false }) };
}

export function applyReviewDetails(rows: ReviewRow[], date: string, lab: string): ReviewRow[] {
  return rows.map(row => ({ ...row, specimen_datetime: date || row.specimen_datetime, lab: lab || row.lab, confirmed: false }));
}

export function pdfReviewExcerpt(rowId: string, pages: LabImportDraft["pages"]): string | null {
  const location = /^p(\d+)-l(\d+)$/.exec(rowId);
  if (!location) return null;
  const page = pages.find(page => page.page === Number(location[1]));
  return page?.text.split(/\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]/)[Number(location[2]) - 1]?.trim() || null;
}

export function reportSpecimenDate(timestamp: string, flags: string[]): string {
  if (flags.includes("date_only")) return timestamp.slice(0, 10);
  return new Date(timestamp).toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC");
}
