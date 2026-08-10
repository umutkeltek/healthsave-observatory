// Shared sleep visualization components used by /sleep and /demo.
// Extracted to avoid duplicating the hypnogram, stage breakdown, and consistency gauge.

import {
  bedtimeLabel,
  durationLabel,
  STAGE_COLOR,
  STAGE_LABEL,
  type SleepNight,
  type SleepSegment,
} from "../lib/sleep";

export function Hypnogram({ segments }: { segments: SleepSegment[] }) {
  if (segments.length === 0) return <p className="empty">No stage data for this night.</p>;
  const segmentLabels = segments.map(
    (segment) =>
      `${STAGE_LABEL[segment.stage] ?? segment.stage} · ${bedtimeLabel(segment.t)}${
        segment.end ? ` → ${bedtimeLabel(segment.end)}` : ""
      }`,
  );
  return (
    <div
      className="sleep-hypno"
      role="img"
      aria-label={`Sleep stage sequence: ${segmentLabels.join("; ")}`}
    >
      {segments.map((seg, i) => (
        <span
          key={i}
          className="sleep-seg"
          aria-hidden="true"
          style={{
            background: STAGE_COLOR[seg.stage] ?? "var(--neutral)",
            flexGrow: seg.durationMin ?? 1,
          }}
          title={segmentLabels[i]}
        />
      ))}
    </div>
  );
}

export function StageBreakdown({ night }: { night: SleepNight }) {
  const stages = ["deep", "core", "light", "rem", "asleep", "awake", "conflict"].filter(
    (stage) => (night.stageMinutes[stage] || 0) > 0,
  );
  // API-derived nights carry the atomic tracked-time union. Static demo data
  // predates that field and its duration is already the full session span.
  const total = night.trackedMin ?? night.durationMin;
  const context = ["in_bed", "unknown"].filter(
    (stage) => (night.stageMinutes[stage] || 0) > 0,
  );
  return (
    <div className="sleep-breakdown">
      {stages.map((stage) => {
        const mins = night.stageMinutes[stage] || 0;
        const pct = total > 0 ? Math.round((mins / total) * 100) : 0;
        return (
          <div key={stage} className="sleep-breakdown-row">
            <span className="sleep-breakdown-dot" style={{ background: STAGE_COLOR[stage] }} />
            <span className="sleep-breakdown-label">{STAGE_LABEL[stage]}</span>
            <span className="sleep-breakdown-bar-wrap">
              <span
                className="sleep-breakdown-bar"
                style={{ width: `${pct}%`, background: STAGE_COLOR[stage] }}
              />
            </span>
            <span className="sleep-breakdown-val mono">
              {Math.round(mins)}m <span className="sleep-breakdown-pct">{pct}%</span>
            </span>
          </div>
        );
      })}
      {context.length > 0 && (
        <p className="meta">
          {context
            .map((stage) => `${STAGE_LABEL[stage]} ${Math.round(night.stageMinutes[stage])}m`)
            .join(" · ")} — contextual states excluded from sleep duration.
        </p>
      )}
      {(night.streamCount ?? 1) > 1 && (
        <p className="meta">
          {night.streamCount} source streams contributed; overlapping clock time is counted once.
        </p>
      )}
      {(night.stageMinutes.conflict || 0) > 0 && (
        <p className="meta">
          {Math.round(night.stageMinutes.conflict)}m had conflicting stage labels and is shown separately.
        </p>
      )}
    </div>
  );
}

export function ConsistencyGauge({ score }: { score: number | null }) {
  if (score === null) return <p className="empty">Need at least 3 nights to measure consistency.</p>;
  const tone = score >= 80 ? "good" : score >= 50 ? "warn" : "down";
  return (
    <div className={`sleep-gauge sleep-gauge-${tone}`}>
      <svg viewBox="0 0 120 120" className="sleep-gauge-ring" role="img" aria-label={`Sleep consistency ${score} of 100`}>
        <circle cx="60" cy="60" r="52" className="sleep-gauge-track" />
        <circle
          cx="60"
          cy="60"
          r="52"
          className="sleep-gauge-fill"
          pathLength={100}
          strokeDasharray={100}
          strokeDashoffset={100 - score}
        />
      </svg>
      <div className="sleep-gauge-readout">
        <span className="sleep-gauge-num">{score}</span>
        <span className="sleep-gauge-cap">consistency</span>
      </div>
    </div>
  );
}

// Compact sleep stat box reused by demo page — renders bedtime/wake times,
// duration label, and an optional delta vs baseline.
export function SleepStatBox({
  bedtime,
  wakeTime,
  durationMin,
  bedDelta,
  wakeDelta,
}: {
  bedtime: string;
  wakeTime: string;
  durationMin: number;
  bedDelta?: number | null;
  wakeDelta?: number | null;
}) {
  return (
    <div className="sleep-hero-lede">
      <h1>{durationLabel(durationMin)}</h1>
      <p className="sleep-hero-meta">
        {bedtimeLabel(bedtime)} → {bedtimeLabel(wakeTime)}
        {(bedDelta != null || wakeDelta != null) && (
          <span className="sleep-delta">
            {" · "}
            {bedDelta != null && `${bedDelta > 0 ? "+" : ""}${bedDelta} min bed`}
            {bedDelta != null && wakeDelta != null && ", "}
            {wakeDelta != null && `${wakeDelta > 0 ? "+" : ""}${wakeDelta} min wake`}
            {" vs usual"}
          </span>
        )}
      </p>
    </div>
  );
}
