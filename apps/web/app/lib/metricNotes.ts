// Honesty footnotes for metrics that are routinely misread. Research-grounded
// (docs/healthResearch): these render on the Library detail page so the caveat
// travels with the number, not buried in docs.

// One plain line shown on the metric's own card, for metrics a reader would
// otherwise mistake for one they already know. RMSSD sits beside SDNN: the
// same words the iPhone app uses, so both surfaces tell one story.
export const METRIC_ONE_LINERS: Record<string, string> = {
  "vital.hrv_rmssd": "A second way to measure HRV. Compare it only with its own past readings.",
};

export function metricOneLiner(metricId: string): string | null {
  return METRIC_ONE_LINERS[metricId] ?? null;
}

export const METRIC_NOTES: Record<string, string[]> = {
  "vital.hrv_sdnn": [
    "SDNN is the HRV measure Apple Watch has always recorded. RMSSD (iPhone on iOS 27, Android, Whoop) is a different measure with its own row - the two are never merged or averaged here.",
    "Read HRV as a 7-day rolling baseline, not a single morning's number: one low reading can be artifact, alcohol, illness, or a late meal.",
  ],
  "vital.hrv_rmssd": [
    "A second way to measure HRV. Compare it only with its own past readings.",
    "RMSSD and SDNN are not on the same scale, so the two are shown side by side, never merged or averaged.",
    "Read it as a 7-day rolling baseline, not a single morning's number: one low reading can be artifact, alcohol, illness, or a late meal.",
  ],
  "vital.blood_oxygen": [
    "A single low SpO₂ reading is noise, not a finding. Patterns across several nights - corroborated by symptoms - are what matter.",
  ],
  "cardio.vo2_max": [
    "Watch VO₂max is an estimate (±~4.7 ml/kg/min). The trend against your own 90-day baseline is the signal; the absolute number is not.",
  ],
  "vital.resting_heart_rate": [
    "Resting HR drifts with heat, alcohol, illness, and training load - judge it against your own baseline band, not population norms.",
  ],
};
