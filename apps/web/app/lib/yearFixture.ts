// Test fixture for the Year in Health view and card: a consistent 2025 summary
// shaped like the API's answer (masks, gap runs that partition every "0",
// months, sources, a device change, per-source headlines). Used by tests only.

import type { YearFamily, YearGap, YearInHealth, YearMonth } from "./api";
import { isoAdd } from "./year";

export const WATCH = "7c1f0c52-4c1b-5d0e-9a43-2a7f7d1b9e01";
export const RING = "0b9d7e1e-34a4-5f39-8d3c-6f1f6a2f0a02";

function gapsOf(mask: string, start: string): YearGap[] {
  const first = mask.indexOf("1");
  const last = mask.lastIndexOf("1");
  if (first < 0) return mask ? [{ start, end: isoAdd(start, mask.length - 1), days: mask.length, kind: "no_data" }] : [];
  const runs: YearGap[] = [];
  let i = 0;
  while (i < mask.length) {
    if (mask[i] === "1") {
      i++;
      continue;
    }
    let j = i;
    while (j + 1 < mask.length && mask[j + 1] === "0") j++;
    const kind = j < first ? "before_first" : i > last ? "after_last" : "inside";
    runs.push({ start: isoAdd(start, i), end: isoAdd(start, j), days: j - i + 1, kind });
    i = j + 1;
  }
  return runs;
}

function family(id: string, label: string, mask: string, start: string): YearFamily {
  const gaps = gapsOf(mask, start);
  const ones = [...mask].filter((c) => c === "1").length;
  const first = mask.indexOf("1");
  const last = mask.lastIndexOf("1");
  return {
    id,
    label,
    metric_ids: [],
    days_with_data: ones,
    days_without_data: mask.length - ones,
    first_day: first < 0 ? null : isoAdd(start, first),
    last_day: last < 0 ? null : isoAdd(start, last),
    mask,
    gaps,
    longest_inside_gap: Math.max(0, ...gaps.filter((g) => g.kind === "inside").map((g) => g.days)),
    confidence: ones / mask.length < 0.5 ? "low" : "ok",
  };
}

/** 2025 with a nine-day August gap, a ring from April 10, a weekly scale. */
export function yearFixture(options: { windowEnd?: string } = {}): YearInHealth {
  const start = "2025-01-01";
  const end = options.windowEnd ?? "2025-12-31";
  const days = Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000) + 1;
  const iso = (i: number) => isoAdd(start, i);
  const inAugustGap = (d: string) => d >= "2025-08-03" && d <= "2025-08-11";
  const heart = Array.from({ length: days }, (_, i) => (inAugustGap(iso(i)) ? "0" : "1")).join("");
  const sleep = Array.from({ length: days }, (_, i) => (iso(i) >= "2025-04-10" && !inAugustGap(iso(i)) ? "1" : "0")).join("");
  const body = Array.from({ length: days }, (_, i) => (i % 7 === 0 && !inAugustGap(iso(i)) ? "1" : "0")).join("");
  const families = [
    family("heart", "Heart and vitals", heart, start),
    family("sleep", "Sleep", sleep, start),
    family("body", "Body measurements", body, start),
  ];
  const counts = Array.from({ length: days }, (_, i) => families.filter((f) => f.mask[i] === "1").length);
  const mask = counts.map((c) => (c > 0 ? "1" : "0")).join("");
  const months: YearMonth[] = Array.from({ length: 12 }, (_, m) => {
    const monthDays = Array.from({ length: days }, (_, i) => i).filter((i) => Number(iso(i).slice(5, 7)) === m + 1);
    const withData = monthDays.filter((i) => mask[i] === "1").length;
    const confidence = monthDays.length === 0 ? "future" : withData === 0 ? "none" : withData / monthDays.length < 0.5 ? "low" : "ok";
    return {
      month: m + 1,
      days: monthDays.length,
      days_with_data: withData,
      coverage: monthDays.length ? withData / monthDays.length : null,
      families: families.filter((f) => monthDays.some((i) => f.mask[i] === "1")).map((f) => f.id),
      source_ids: m + 1 >= 4 ? [WATCH, RING] : [WATCH],
      first_seen_ids: m + 1 === 4 ? [RING] : [],
      last_seen_ids: [],
      confidence,
    };
  });
  const daysWithData = [...mask].filter((c) => c === "1").length;
  const overallGaps = gapsOf(mask, start);
  return {
    year: 2025,
    owner_id: "00000000-0000-0000-0000-000000000001",
    time_zone: "Europe/Istanbul",
    day_boundary: "04:00",
    generated_at: "2025-12-31T12:00:00Z",
    window_start: start,
    window_end: end,
    days_in_window: days,
    days_with_data: daysWithData,
    first_day: "2025-01-01",
    last_day: end,
    day_family_counts: counts,
    mask,
    gaps: overallGaps,
    longest_inside_gap: Math.max(0, ...overallGaps.filter((g) => g.kind === "inside").map((g) => g.days)),
    months,
    families,
    sources: [
      {
        stream_id: WATCH,
        label: "Sam's Apple Watch",
        source_plugin_id: "apple_health",
        first_day: "2025-01-01",
        last_day: end,
        days_with_data: daysWithData,
        months: Array.from({ length: 12 }, (_, m) => m + 1),
        families: ["heart", "body"],
        first_seen_at: "2023-05-02T06:00:00Z",
        last_seen_at: `${end}T06:00:00Z`,
        new_this_year: false,
        stopped_this_year: false,
      },
      {
        stream_id: RING,
        label: "Oura <Ring> & Co",
        source_plugin_id: "apple_health",
        first_day: "2025-04-10",
        last_day: end,
        days_with_data: [...sleep].filter((c) => c === "1").length,
        months: [4, 5, 6, 7, 8, 9, 10, 11, 12],
        families: ["sleep"],
        first_seen_at: "2025-04-10T06:00:00Z",
        last_seen_at: `${end}T06:00:00Z`,
        new_this_year: true,
        stopped_this_year: false,
      },
    ],
    device_changes: [{ day: "2025-04-10", kind: "first_seen", stream_id: RING, label: "Oura <Ring> & Co" }],
    headlines: [
      { id: "days_recorded", label: "Days with any data", value: daysWithData, unit: "days", stream_id: null, source_label: null, low: null, high: null, days: daysWithData, of_days: days, basis: "count", confidence: "ok" },
      { id: "sources", label: "Sources", value: 2, unit: "sources", stream_id: null, source_label: null, low: null, high: null, days: null, of_days: null, basis: "count", confidence: "ok" },
      { id: "longest_gap", label: "Longest stretch with nothing recorded", value: 9, unit: "days", stream_id: null, source_label: null, low: null, high: null, days: null, of_days: null, basis: "count", confidence: "ok" },
      { id: "resting_heart_rate", label: "Resting heart rate", value: 56, unit: "bpm", stream_id: WATCH, source_label: "Sam's Apple Watch", low: 52, high: 61, days: 341, of_days: null, basis: "median_one_source", confidence: "ok" },
      { id: "resting_heart_rate", label: "Resting heart rate", value: 50, unit: "bpm", stream_id: RING, source_label: "Oura <Ring> & Co", low: 47, high: 54, days: 22, of_days: null, basis: "median_one_source", confidence: "low" },
      { id: "steps", label: "Daily steps", value: 8437, unit: "steps", stream_id: null, source_label: "All sources, daily total", low: 4210, high: 12880, days: 356, of_days: null, basis: "median_all_sources_total", confidence: "ok" },
    ],
    withheld: [{ id: "resting_heart_rate", label: "Resting heart rate", stream_id: null, source_label: "Old Scale", days: 4, reason: "too_few_days" }],
    limitations: [
      { code: "time_basis", day: null, count: null },
      { code: "day_presence_only", day: null, count: null },
      { code: "device_labels", day: null, count: null },
      { code: "headline_thin", day: null, count: null },
    ],
    confidence: "ok",
  };
}
