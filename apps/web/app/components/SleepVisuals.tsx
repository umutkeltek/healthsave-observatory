// Shared sleep visualization components used by /sleep and /demo.
// Extracted to avoid duplicating the hypnogram, stage breakdown, and consistency gauge.

import { bedtimeLabel, STAGE_COLOR, STAGE_LABEL, type SleepNight, type SleepSegment } from "../lib/sleep";

export function Hypnogram({ segments }: { segments: SleepSegment[] }) {
  if (segments.length === 0) return <p className="empty">No stage data for this night.</p>;
  return (
    <div className="sleep-hypno" role="img" aria-label="Sleep stage hypnogram">
      {segments.map((seg, i) => (
        <span
          key={i}
          className="sleep-seg"
          aria-hidden="true"
          style={{ background: STAGE_COLOR[seg.stage] ?? "var(--neutral)" }}
          title={`${STAGE_LABEL[seg.stage] ?? seg.stage} · ${new Date(seg.t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`}
        />
      ))}
    </div>
  );
}

export function StageBreakdown({ night }: { night: SleepNight }) {
  const stages = ["deep", "core", "rem", "awake"] as const;
  const total = Object.values(night.stageMinutes).reduce((a, b) => a + b, 0);
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
  const h = Math.floor(durationMin / 60);
  const m = Math.round(durationMin % 60);
  return (
    <div className="sleep-hero-lede">
      <h1>{h}h {m}m</h1>
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
