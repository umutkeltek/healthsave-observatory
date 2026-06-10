// Honesty footnotes for metrics that are routinely misread. Research-grounded
// (docs/healthResearch): these render on the Library detail page so the caveat
// travels with the number, not buried in docs.

export const METRIC_NOTES: Record<string, string[]> = {
  "vital.hrv_sdnn": [
    "Apple reports SDNN; Whoop reports RMSSD. They measure different things and are never merged here — when both stream, you see both.",
    "Read HRV as a 7-day rolling baseline, not a single morning's number: one low reading can be artifact, alcohol, illness, or a late meal.",
  ],
  "vital.blood_oxygen": [
    "A single low SpO₂ reading is noise, not a finding. Patterns across several nights — corroborated by symptoms — are what matter.",
  ],
  "cardio.vo2_max": [
    "Watch VO₂max is an estimate (±~4.7 ml/kg/min). The trend against your own 90-day baseline is the signal; the absolute number is not.",
  ],
  "vital.resting_heart_rate": [
    "Resting HR drifts with heat, alcohol, illness, and training load — judge it against your own baseline band, not population norms.",
  ],
};
