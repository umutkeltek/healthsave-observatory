import type { Metadata } from "next";

import { BaselineRibbon } from "../components/BaselineRibbon";
import { ConsistencyGauge, Hypnogram, StageBreakdown } from "../components/SleepVisuals";
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
  type SleepNight,
} from "../lib/sleep";

export const revalidate = 30;
export const metadata: Metadata = { title: "Sleep · HealthSave Observatory" };

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
            Apple Watch tracks sleep automatically. Open HealthSave → Settings → Server Sync to stream
            your nights here.
          </p>
          <div style={{ marginTop: 16, display: "flex", gap: 12 }}>
            <a href="/" className="btn btn-ghost">
              ← Today
            </a>
            <a href="/demo" className="btn btn-ghost">
              Explore demo →
            </a>
          </div>
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
                    {(bedDelta !== null || wakeDelta !== null) && (
                      <span className="sleep-delta">
                        {" · "}
                        {bedDelta !== null && `${bedDelta > 0 ? "+" : ""}${bedDelta} min bed`}
                        {bedDelta !== null && wakeDelta !== null && ", "}
                        {wakeDelta !== null && `${wakeDelta > 0 ? "+" : ""}${wakeDelta} min wake`}
                        {" vs usual"}
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
