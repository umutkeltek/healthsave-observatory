import type { SeriesPoint } from "./api";

// A single sleep night, derived from raw sleep.stage samples.
export type SleepNight = {
  date: string; // ISO date of the night (bedtime date)
  bedtime: string; // ISO datetime of first stage
  wakeTime: string; // ISO datetime of last stage
  durationMin: number; // total sleep duration in minutes
  trackedMin?: number; // union of asleep + awake clock time; omitted by static demo data
  timeInBedMin?: number; // union of in-bed + asleep + awake clock time; omitted by static demo data
  stageMinutes: Record<string, number>; // minutes in each stage
  segments: SleepSegment[]; // ordered stage blocks
  streamCount?: number; // distinct source streams represented in this night
};

export type SleepSegment = {
  t: string; // ISO datetime
  end?: string; // ISO datetime; omitted only by static demo data
  durationMin?: number; // true interval duration; omitted only by static demo data
  stage: string; // awake, rem, core, deep, or a preserved source state
};

type ParsedSleepSegment = SleepSegment & {
  end: string;
  durationMin: number;
  startMs: number;
  endMs: number;
  streamKey: string;
};

const MAX_SEGMENT_MINUTES = 24 * 60;
const DETAILED_ASLEEP_STAGES = ["core", "deep", "rem", "light"] as const;
const CONTEXT_STAGES = ["in_bed", "unknown"] as const;

function normalizeStage(code: string): string {
  const normalized = code.trim().toLowerCase().replace(/[\s-]+/g, "_");
  return normalized === "asleep_unspecified" ? "asleep" : normalized;
}

function parsedSegment(point: SeriesPoint): ParsedSleepSegment | null {
  if (typeof point.code !== "string" || typeof point.interval_end !== "string") return null;
  const startMs = Date.parse(point.t);
  const endMs = Date.parse(point.interval_end);
  const durationMin = (endMs - startMs) / 60_000;
  if (
    !Number.isFinite(startMs) ||
    !Number.isFinite(endMs) ||
    durationMin <= 0 ||
    durationMin > MAX_SEGMENT_MINUTES
  ) {
    return null;
  }
  const sourceId = typeof point.source_id === "string" ? point.source_id : "unknown-source";
  const streamId = typeof point.stream_id === "string" ? point.stream_id : null;
  return {
    t: point.t,
    end: point.interval_end,
    stage: normalizeStage(point.code),
    durationMin,
    startMs,
    endMs,
    streamKey: streamId || sourceId,
  };
}

type TimelineReconciliation = {
  durationMin: number;
  trackedMin: number;
  timeInBedMin: number;
  stageMinutes: Record<string, number>;
  segments: SleepSegment[];
};

function reconcileTimeline(parsed: ParsedSleepSegment[]): TimelineReconciliation {
  const events = new Map<number, Map<string, number>>();
  const addEvent = (at: number, stage: string, delta: number) => {
    const changes = events.get(at) ?? new Map<string, number>();
    changes.set(stage, (changes.get(stage) ?? 0) + delta);
    events.set(at, changes);
  };
  for (const segment of parsed) {
    addEvent(segment.startMs, segment.stage, 1);
    addEvent(segment.endMs, segment.stage, -1);
  }

  const boundaries = [...events.keys()].sort((a, b) => a - b);
  const active = new Map<string, number>();
  const minutesByStage = new Map<string, number>();
  const visual: Array<{ startMs: number; endMs: number; stage: string }> = [];
  let durationMin = 0;
  let trackedMin = 0;
  let timeInBedMin = 0;

  const addMinutes = (stage: string, minutes: number) => {
    minutesByStage.set(stage, (minutesByStage.get(stage) ?? 0) + minutes);
  };

  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const startMs = boundaries[index];
    for (const [stage, delta] of events.get(startMs) ?? []) {
      const nextCount = (active.get(stage) ?? 0) + delta;
      if (nextCount > 0) active.set(stage, nextCount);
      else active.delete(stage);
    }

    const endMs = boundaries[index + 1];
    const sliceMin = (endMs - startMs) / 60_000;
    if (sliceMin <= 0) continue;

    const detailedStages = DETAILED_ASLEEP_STAGES.filter((stage) => active.has(stage));
    const hasGenericAsleep = active.has("asleep");
    const hasAsleep = detailedStages.length > 0 || hasGenericAsleep;
    const hasAwake = active.has("awake");
    const hasInBed = active.has("in_bed");
    let displayStage: string | null = null;

    if (hasAsleep) {
      // Total sleep follows the legacy sleep_sessions contract: any asleep
      // classification makes this clock slice asleep. Generic asleep is
      // compatible with one detailed classification; only incompatible detail
      // or an awake/asleep disagreement is exposed as a conflict.
      durationMin += sliceMin;
      trackedMin += sliceMin;
      if (hasAwake || detailedStages.length > 1) {
        displayStage = "conflict";
      } else if (detailedStages.length === 1) {
        displayStage = detailedStages[0];
      } else {
        displayStage = "asleep";
      }
      addMinutes(displayStage, sliceMin);
    } else if (hasAwake) {
      trackedMin += sliceMin;
      displayStage = "awake";
      addMinutes("awake", sliceMin);
    } else if (hasInBed) {
      displayStage = "in_bed";
    } else if (active.has("unknown")) {
      displayStage = "unknown";
    }

    if (hasInBed || hasAsleep || hasAwake) timeInBedMin += sliceMin;

    // These are contextual source states, not evidence of sleep. Preserve
    // their union for disclosure while excluding them from sleep duration and
    // stage-percentage denominators.
    for (const stage of CONTEXT_STAGES) {
      if (active.has(stage)) addMinutes(stage, sliceMin);
    }

    if (displayStage) {
      const previous = visual.at(-1);
      if (previous?.stage === displayStage && previous.endMs === startMs) {
        previous.endMs = endMs;
      } else {
        visual.push({ startMs, endMs, stage: displayStage });
      }
    }
  }

  return {
    durationMin,
    trackedMin,
    timeInBedMin,
    stageMinutes: Object.fromEntries(minutesByStage),
    segments: visual.map(({ startMs, endMs, stage }) => ({
      t: new Date(startMs).toISOString(),
      end: new Date(endMs).toISOString(),
      durationMin: (endMs - startMs) / 60_000,
      stage,
    })),
  };
}

// Group raw sleep stage points into nights. A night boundary is noon UTC
// (the analytical-time default): any stage before noon belongs to the
// previous calendar date's night. Stages are bucketed by their date key.
//
// ── Noon-split heuristic ──────────────────────────────────────────────
// This heuristic is necessary because Apple Watch sleep data from HealthSave
// arrives as independent sleep.stage intervals — there is no per-night
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
    const instant = Date.parse(p.t);
    if (!Number.isFinite(instant)) continue;
    const t = new Date(instant);
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

export function deriveNight(key: string, points: SeriesPoint[]): SleepNight | null {
  const parsed = points
    .map(parsedSegment)
    .filter((segment): segment is ParsedSleepSegment => segment !== null)
    .sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs);
  if (parsed.length === 0) return null;

  const { durationMin, trackedMin, timeInBedMin, stageMinutes, segments } =
    reconcileTimeline(parsed);

  if (durationMin < MIN_NIGHT_MINUTES) return null;

  const bedtime = parsed[0].t;
  const wake = parsed.reduce((latest, segment) => segment.endMs > latest.endMs ? segment : latest);
  const wakeTime = wake.end;

  const streamCount = new Set(parsed.map((segment) => segment.streamKey)).size;

  return {
    date: key,
    bedtime,
    wakeTime,
    durationMin,
    trackedMin,
    timeInBedMin,
    stageMinutes,
    segments,
    streamCount,
  };
}

export type SleepTrend = {
  dates: string[];
  durations: number[];
  bedtimes: string[];
  waketimes: string[];
  efficiencies: number[]; // asleep / time in bed, as a percentage
};

export function sleepTrends(nights: SleepNight[]): SleepTrend {
  const sorted = [...nights].sort((a, b) => a.date.localeCompare(b.date));
  return {
    dates: sorted.map((n) => n.date),
    durations: sorted.map((n) => n.durationMin),
    bedtimes: sorted.map((n) => n.bedtime),
    waketimes: sorted.map((n) => n.wakeTime),
    efficiencies: sorted.map((n) => {
      const intervalDenominator = n.timeInBedMin ?? n.trackedMin;
      if (intervalDenominator !== undefined) {
        return intervalDenominator > 0 ? (n.durationMin / intervalDenominator) * 100 : 0;
      }
      // Static demo fixtures predate interval unions: their duration is the
      // session span and therefore already includes awake time.
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
  const rounded = Math.max(0, Math.round(minutes));
  const h = Math.floor(rounded / 60);
  const m = rounded % 60;
  return `${h}h ${m}m`;
}

export const STAGE_COLOR: Record<string, string> = {
  awake: "var(--sleep-awake)",
  rem: "var(--sleep-rem)",
  core: "var(--sleep-core)",
  deep: "var(--sleep-deep)",
  light: "var(--sleep-core)",
  asleep: "var(--sleep-core)",
  in_bed: "var(--neutral)",
  unknown: "var(--neutral)",
  conflict: "var(--warn)",
};

export const STAGE_LABEL: Record<string, string> = {
  awake: "Awake",
  rem: "REM",
  core: "Core",
  deep: "Deep",
  light: "Light",
  asleep: "Asleep (stage unspecified)",
  in_bed: "In Bed",
  unknown: "Unknown",
  conflict: "Conflicting stages",
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

// Compute last night's bedtime/wake clock-time change vs. the circular mean of
// prior nights. Comparing epoch timestamps would accidentally include the days
// between nights and report shifts measured in thousands of minutes.
export function bedtimeDelta(trend: SleepTrend): { bedDelta: number | null; wakeDelta: number | null } {
  if (trend.bedtimes.length < 2) return { bedDelta: null, wakeDelta: null };

  const clockMinutes = (iso: string): number => {
    const date = new Date(iso);
    return date.getUTCHours() * 60 + date.getUTCMinutes();
  };
  const circularMeanMinutes = (values: number[]): number => {
    const angles = values.map((value) => (value / 1440) * 2 * Math.PI);
    const sin = angles.reduce((sum, angle) => sum + Math.sin(angle), 0);
    const cos = angles.reduce((sum, angle) => sum + Math.cos(angle), 0);
    const angle = Math.atan2(sin / values.length, cos / values.length);
    return (((angle < 0 ? angle + 2 * Math.PI : angle) / (2 * Math.PI)) * 1440) % 1440;
  };
  const shortestClockDelta = (value: number, baseline: number): number => {
    const raw = value - baseline;
    return Math.round(((raw + 720) % 1440 + 1440) % 1440 - 720);
  };

  const lastBed = clockMinutes(trend.bedtimes[trend.bedtimes.length - 1]);
  const lastWake = clockMinutes(trend.waketimes[trend.waketimes.length - 1]);
  const priorBedMean = circularMeanMinutes(trend.bedtimes.slice(0, -1).map(clockMinutes));
  const priorWakeMean = circularMeanMinutes(trend.waketimes.slice(0, -1).map(clockMinutes));
  return {
    bedDelta: shortestClockDelta(lastBed, priorBedMean),
    wakeDelta: shortestClockDelta(lastWake, priorWakeMean),
  };
}
