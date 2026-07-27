import type { SeriesPoint } from "./api";

// A single sleep night, derived from raw sleep.stage samples.
export type SleepNight = {
  date: string; // ISO date of the night (bedtime date)
  bedtime: string; // ISO datetime of first stage
  wakeTime: string; // ISO datetime of last stage
  durationMin: number; // total sleep duration in minutes
  stageMinutes: Record<string, number>; // minutes in each stage
  segments: SleepSegment[]; // ordered stage blocks
};

export type SleepSegment = {
  t: string; // ISO datetime
  stage: string; // awake, rem, core, deep
};

// Group raw sleep stage points into nights. A night boundary is noon UTC
// (the analytical-time default): any stage before noon belongs to the
// previous calendar date's night. Stages are bucketed by their date key.
//
// ── Noon-split heuristic ──────────────────────────────────────────────
// This heuristic is necessary because Apple Watch sleep data from HealthSave
// arrives as independent ~30 s sleep.stage samples — there is no per-night
// "bedtime" / "waketime" envelope. The noon split is a robust default:
// virtually all sleep ends well before noon and begins well after noon, so
// the boundary is unambiguous for 99% of nights.
//
// TODO: when the HealthSave iOS ingest pipeline starts streaming per-night
// bedtime/waketime timestamps (planned for the full-export payload format),
// switch `groupSleepNights` to use those deterministic boundaries. At that
// point the noon split becomes a fallback for sources that don't emit
// per-night metadata, and the derivation is exact rather than heuristic.
export function groupSleepNights(points: SeriesPoint[]): Map<string, SeriesPoint[]> {
  const nights = new Map<string, SeriesPoint[]>();
  for (const p of points) {
    const t = new Date(p.t);
    // Noon split: if before 12:00, it's still "last night"
    if (t.getUTCHours() < 12) t.setUTCDate(t.getUTCDate() - 1);
    const key = t.toISOString().slice(0, 10); // YYYY-MM-DD
    const arr = nights.get(key) || [];
    arr.push(p);
    nights.set(key, arr);
  }
  return nights;
}

// Minimum minutes of stage data to count as a valid night.
const MIN_NIGHT_MINUTES = 60;
const MIN_SEGMENTS = 5;

export function deriveNight(key: string, points: SeriesPoint[]): SleepNight | null {
  const sorted = [...points].sort(
    (a, b) => new Date(a.t).getTime() - new Date(b.t).getTime(),
  );

  if (sorted.length < MIN_SEGMENTS) return null;

  const segments: SleepSegment[] = sorted
    .filter((p) => p.code !== null)
    .map((p) => ({ t: p.t, stage: p.code! }));

  const bedtime = segments[0].t;
  const wakeTime = segments[segments.length - 1].t;
  const durationMin =
    (new Date(wakeTime).getTime() - new Date(bedtime).getTime()) / 60000;

  if (durationMin < MIN_NIGHT_MINUTES) return null;

  const stageMinutes: Record<string, number> = {};
  for (const seg of segments) {
    stageMinutes[seg.stage] = (stageMinutes[seg.stage] || 0) + 0.5; // ~30s samples
  }

  return { date: key, bedtime, wakeTime, durationMin, stageMinutes, segments };
}

export type SleepTrend = {
  dates: string[];
  durations: number[];
  bedtimes: string[];
  waketimes: string[];
  efficiencies: number[]; // (total - awake) / total as %
};

export function sleepTrends(nights: SleepNight[]): SleepTrend {
  const sorted = [...nights].sort((a, b) => a.date.localeCompare(b.date));
  return {
    dates: sorted.map((n) => n.date),
    durations: sorted.map((n) => n.durationMin),
    bedtimes: sorted.map((n) => n.bedtime),
    waketimes: sorted.map((n) => n.wakeTime),
    efficiencies: sorted.map((n) => {
      const awake = n.stageMinutes.awake || 0;
      return n.durationMin > 0 ? ((n.durationMin - awake) / n.durationMin) * 100 : 0;
    }),
  };
}

export function bedtimeLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function durationLabel(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `${h}h ${m}m`;
}

export const STAGE_COLOR: Record<string, string> = {
  awake: "var(--sleep-awake)",
  rem: "var(--sleep-rem)",
  core: "var(--sleep-core)",
  deep: "var(--sleep-deep)",
};

export const STAGE_LABEL: Record<string, string> = {
  awake: "Awake",
  rem: "REM",
  core: "Core",
  deep: "Deep",
};

// Score sleep consistency — lower variance = higher score. Returns 0-100 where
// 100 = bed/wake within ~30 min every night. Uses circular mean for clock times
// so a schedule at 23:00 and 01:00 is correctly measured as 2h apart, not 22h.
// Sample std (N-1) since we only require 3 nights of data.
export function consistencyScore(trend: SleepTrend): number | null {
  if (trend.bedtimes.length < 3) return null;

  const toMinutes = (iso: string): number => {
    const d = new Date(iso);
    return d.getUTCHours() * 60 + d.getUTCMinutes();
  };

  const bedMins = trend.bedtimes.map(toMinutes);
  const wakeMins = trend.waketimes.map(toMinutes);
  const n = bedMins.length;

  // Circular std — treat minutes as angles on a 24h (1440 min) circle.
  const circularStd = (mins: number[]): number => {
    const angles = mins.map((m) => (m / 1440) * 2 * Math.PI);
    const sinSum = angles.reduce((s, a) => s + Math.sin(a), 0);
    const cosSum = angles.reduce((s, a) => s + Math.cos(a), 0);
    const R = Math.sqrt(sinSum * sinSum + cosSum * cosSum) / n;
    // R = 1 (all same angle) → std = 0; R → 0 → std blows up; 1-R maps 0→1 sensibly.
    // Convert radians back to minutes: sqrt(-2 * ln(R)) * (1440 / (2π))
    // For small variance, 1-R ≈ variance/2, so std ≈ sqrt(2*(1-R)) * 1440/(2π)
    const clampR = Math.min(1, Math.max(0, R));
    const angularStd = clampR < 0.999
      ? Math.sqrt(-2 * Math.log(clampR)) * (1440 / (2 * Math.PI))
      : 0;
    return Math.min(angularStd, 720); // cap at 12h
  };

  const bedStd = circularStd(bedMins);
  const wakeStd = circularStd(wakeMins);
  const avgStd = (bedStd + wakeStd) / 2;
  // 0 min variance → 100, 180 min variance → 0
  return Math.max(0, Math.round(100 - (avgStd / 180) * 100));
}

// Sleep debt: cumulative shortfall vs. 8h target over the window.
export function sleepDebt(trend: SleepTrend): number | null {
  if (trend.durations.length === 0) return null;
  const targetMin = 480; // 8 hours
  const debt = trend.durations.reduce((sum, d) => sum + (targetMin - d), 0);
  return Math.max(0, Math.round(debt / 60)); // hours; floors at 0
}

// Compute last night's bedtime/wake time change vs. average of prior nights.
export function bedtimeDelta(trend: SleepTrend): { bedDelta: number | null; wakeDelta: number | null } {
  if (trend.bedtimes.length < 2) return { bedDelta: null, wakeDelta: null };
  const lastBed = new Date(trend.bedtimes[trend.bedtimes.length - 1]);
  const lastWake = new Date(trend.waketimes[trend.waketimes.length - 1]);
  const priorBeds = trend.bedtimes.slice(0, -1).map((t) => new Date(t).getTime());
  const priorWakes = trend.waketimes.slice(0, -1).map((t) => new Date(t).getTime());
  const avgBed = priorBeds.reduce((a, b) => a + b) / priorBeds.length;
  const avgWake = priorWakes.reduce((a, b) => a + b) / priorWakes.length;
  return {
    bedDelta: Math.round((lastBed.getTime() - avgBed) / 60000),
    wakeDelta: Math.round((lastWake.getTime() - avgWake) / 60000),
  };
}
