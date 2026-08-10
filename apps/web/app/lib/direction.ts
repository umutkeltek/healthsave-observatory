// Per-metric "which way is good" — drives honest directional colour on cards.
//
// A recovery/health metric moving *up* is not universally good: a rising HRV is
// great, a rising resting heart rate is not. Cards that tint a delta need to
// know the metric's direction or they will lie for roughly half the catalogue.
//
// `positiveIsGoodFor` returns:
//   true  — higher values are better (HRV, steps, blood oxygen, …)
//   false — lower values are better (resting HR, respiratory rate, asymmetry, …)
//   null  — we don't know; callers should render a neutral tone rather than guess.
//
// Sources, in priority order: explicit map below, then the reference threshold
// bands in analytics.ts (a metric whose top band is "ok" is higher-is-better).

import { THRESHOLDS } from "./analytics";

const LOWER_IS_BETTER = new Set([
  "vital.resting_heart_rate",
  "vital.walking_heart_rate_average",
  "vital.heart_rate",
  "vital.respiratory_rate",
  "vital.body_temperature",
  "vital.blood_pressure_systolic",
  "vital.blood_pressure_diastolic",
  "mobility.walking_asymmetry",
  "sleep.awake",
]);

const HIGHER_IS_BETTER = new Set([
  "vital.hrv_sdnn",
  "vital.blood_oxygen",
  "activity.steps",
  "activity.exercise_minutes",
  "activity.active_energy",
  "activity.distance",
  "mobility.walking_speed",
  "mobility.walking_step_length",
  "vital.vo2_max",
]);

function fromThresholds(metricId: string): boolean | null {
  const bands = THRESHOLDS[metricId];
  if (!bands?.length) return null;
  // The top reference band being "ok" means high values are desirable.
  return bands[bands.length - 1].tone === "ok";
}

export function positiveIsGoodFor(metricId: string): boolean | null {
  if (LOWER_IS_BETTER.has(metricId)) return false;
  if (HIGHER_IS_BETTER.has(metricId)) return true;
  return fromThresholds(metricId);
}
