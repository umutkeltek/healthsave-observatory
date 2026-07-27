import type { Metadata } from "next";

import { BaselineRibbon } from "../components/BaselineRibbon";
import { safeSeries } from "../lib/load";
import {
  bedtimeDelta,
  bedtimeLabel,
  consistencyScore,
  deriveNight,
  durationLabel,
  groupSleepNights,
  sleepDebt,
  sleepTrends,
  STAGE_COLOR,
  STAGE_LABEL,
  type SleepNight,
  type SleepSegment,
} from "../lib/sleep";

export const revalidate = 30;
export const metadata: Metadata = { title: "Sleep · HealthSave Observatory" };

function Hypnogram({ segments }: { segments: SleepSegment[] }) {
  if (segments.length === 0) return <p className="empty">No stage data for this night.</p>;
  return (
    <div className="sleep-hypno" role="img" aria-label="Sleep stage hypnogram">
      {segments.map((seg, i) => (
        <span
          key={i}
          className="sleep-seg"
          style={{ background: STAGE_COLOR[seg.stage] ?? "var(--neutral)" }}
          title={`${STAGE_LABEL[seg.stage] ?? seg.stage} · ${new Date(seg.t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`}
        />
      ))}
    </div>
  );
}

function StageBreakdown({ night }: { night: SleepNight }) {
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

function ConsistencyGauge({ score }: { score: number | null }) {
  if (score === null) return <p className="empty">Need at least 3 nights to measure consistency.</p>;
  const tone = score >= 80 ? "good" : score >= 50 ? "warn" : "down";
  return (
    <div className={`sleep-gauge sleep-gauge-${tone}`}>
      <svg viewBox="0 0 120 120" className="sleep-gauge-ring">
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

export default async function SleepPage() {
  const series = await safeSeries("sleep.stage", "30d");

  if (!series || series.points.length === 0) {
    return (
      <section className="lead">
        <article className="hero sleep-hero firstrun">
          <div className="hero-eyebrow">Sleep</div>
          <h2>No sleep data yet</h2>
          <p className="recovery-line">
            Sync sleep data from HealthSave to see your nightly patterns, stage breakdown, and trends.
          </p>
          <p className="empty">
            Apple Watch tracks sleep automatically. Once HealthSave syncs, your hypnogram and sleep
            trends appear here.
          </p>
        </article>
      </section>
    );
  }

  const nightsMap = groupSleepNights(series.points);
  const nights: SleepNight[] = [];
  for (const [key, points] of nightsMap) {
    const night = deriveNight(key, points);
    if (night) nights.push(night);
  }
  nights.sort((a, b) => b.date.localeCompare(a.date));

  const lastNight = nights[0];
  const trend = sleepTrends(nights);
  const consistency = consistencyScore(trend);
  const debt = sleepDebt(trend);
  const { bedDelta, wakeDelta } = bedtimeDelta(trend);

  // Duration array for baseline ribbon
  const durationValues = trend.durations;
  const sortedDurations = [...durationValues].sort((a, b) => a - b);

  return (
    <div className="sleep-page">
      {/* Hero: last night */}
      <section className="lead">
        <article className="hero sleep-hero">
          <div className="hero-eyebrow">Last night</div>
          {lastNight ? (
            <>
              <div className="sleep-hero-main">
                <div className="sleep-hero-lede">
                  <h1>{durationLabel(lastNight.durationMin)}</h1>
                  <p className="sleep-hero-meta">
                    {bedtimeLabel(lastNight.bedtime)} → {bedtimeLabel(lastNight.wakeTime)}
                    {bedDelta !== null && (
                      <span className={`sleep-delta ${bedDelta > 30 ? "warn" : ""}`}>
                        {" · "}
                        {bedDelta > 0 ? "+" : ""}
                        {bedDelta} min vs usual
                      </span>
                    )}
                  </p>
                  <Hypnogram segments={lastNight.segments} />
                </div>
                <div className="sleep-hero-side">
                  <StageBreakdown night={lastNight} />
                </div>
              </div>
            </>
          ) : (
            <p className="empty">Not enough data to identify a complete night.</p>
          )}
        </article>
      </section>

      {/* Stats row */}
      <section className="sleep-stats-row">
        <article className="card sleep-stat-card">
          <span className="sleep-stat-label">Consistency</span>
          <ConsistencyGauge score={consistency} />
        </article>
        <article className="card sleep-stat-card">
          <span className="sleep-stat-label">Sleep debt</span>
          {debt !== null ? (
            <div className={`sleep-debt ${debt > 0 ? "warn" : "good"}`}>
              <strong>{debt > 0 ? `+${debt}h` : "0h"}</strong>
              <span>{debt > 0 ? "behind 8h target" : "on track"}</span>
            </div>
          ) : (
            <p className="empty">Need more data.</p>
          )}
        </article>
        <article className="card sleep-stat-card">
          <span className="sleep-stat-label">Efficiency</span>
          {trend.efficiencies.length > 0 ? (
            <div className="sleep-debt good">
              <strong>{Math.round(trend.efficiencies[trend.efficiencies.length - 1])}%</strong>
              <span>last night</span>
            </div>
          ) : (
            <p className="empty">No data.</p>
          )}
        </article>
        <article className="card sleep-stat-card">
          <span className="sleep-stat-label">Avg duration</span>
          {sortedDurations.length > 0 ? (
            <div className="sleep-debt">
              <strong>{durationLabel(Math.round(sortedDurations.reduce((a, b) => a + b) / sortedDurations.length))}</strong>
              <span>{trend.dates.length} nights</span>
            </div>
          ) : (
            <p className="empty">No data.</p>
          )}
        </article>
      </section>

      {/* 30-day duration trend */}
      {durationValues.length >= 3 && (
        <section className="lead">
          <article className="card">
            <h2>30-day duration trend</h2>
            <BaselineRibbon
              values={durationValues}
              height={132}
              axis={["30 days ago", "today"]}
              hoverLabels={trend.dates.map((d) =>
                new Date(d + "T12:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric" }),
              )}
              unit="min"
              ariaLabel="Sleep duration over the last 30 days against your personal baseline"
            />
          </article>
        </section>
      )}

      {/* How to read this */}
      <section className="lead">
        <article className="card">
          <h2>How to read this</h2>
          <div className="sleep-notes">
            <div className="sleep-note">
              <strong>Hypnogram.</strong> Each thin bar represents ~30 seconds of sleep. Colours match standard sleep stages:{" "}
              <span style={{ color: "var(--sleep-deep)" }}>deep</span>,{" "}
              <span style={{ color: "var(--sleep-core)" }}>core</span>,{" "}
              <span style={{ color: "var(--sleep-rem)" }}>REM</span>, and{" "}
              <span style={{ color: "var(--sleep-awake)" }}>awake</span>. A typical night cycles through these ~4–6 times.
            </div>
            <div className="sleep-note">
              <strong>Consistency.</strong> A score from 0–100 that measures how regular your bedtime and wake time are.{" "}
              80+ is excellent — you go to bed and wake up within ~30 minutes of the same time each night.{" "}
              Below 50 means your schedule varies widely and your circadian rhythm may feel the shift.
            </div>
            <div className="sleep-note">
              <strong>Sleep debt.</strong> The cumulative shortfall against an 8-hour target over the visible window.{" "}
              Positive hours means you&apos;re behind — a few hours is normal after a short night, a double-digit debt deserves attention.
            </div>
            <div className="sleep-note">
              <strong>Efficiency.</strong> Time asleep ÷ time in bed. 85%+ is typical for healthy adults.{" "}
              Fragmented sleep (many awake segments) drives this number down.
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}
