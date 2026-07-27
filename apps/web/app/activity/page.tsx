import type { Metadata } from "next";
import { Suspense } from "react";

import { BaselineRibbon } from "../components/BaselineRibbon";
import { CountUp } from "../components/CountUp";
import { CardSkeleton } from "../components/Skeletons";
import { agoLabel, safeSeries, safeSeriesMany } from "../lib/load";
import { summarizeNumericSeries } from "../lib/series";

export const revalidate = 30;
export const metadata: Metadata = { title: "Activity · HealthSave Observatory" };

function numberLabel(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 10000) return (value / 1000).toFixed(1) + "k";
  if (abs >= 1000) return Math.round(value).toLocaleString();
  return abs < 10 && !Number.isInteger(value) ? value.toFixed(1) : Math.round(value).toLocaleString();
}

type StrainCard = {
  metricId: string;
  title: string;
  unit: string;
  icon: string;
  tone?: "neutral" | "up" | "warn";
};

const STRAIN_CARDS: StrainCard[] = [
  { metricId: "activity.steps", title: "Steps", unit: "steps", icon: "👣" },
  { metricId: "activity.exercise_minutes", title: "Exercise", unit: "min", icon: "🏃" },
  { metricId: "activity.active_energy", title: "Active energy", unit: "kcal", icon: "🔥" },
  { metricId: "vital.resting_heart_rate", title: "Resting HR", unit: "bpm", icon: "❤️" },
  { metricId: "vital.walking_heart_rate_average", title: "Walking HR", unit: "bpm", icon: "🚶", tone: "warn" },
];

function StrainSectionFallback() {
  return (
    <div className="activity-grid">
      {STRAIN_CARDS.map((card) => (
        <article key={card.metricId} className="card skeleton-card" aria-hidden>
          <div className="sk sk-eyebrow" />
          <div className="sk sk-line lg" style={{ height: 32, maxWidth: 100 }} />
          <div className="sk sk-line sm" style={{ maxWidth: "60%" }} />
        </article>
      ))}
    </div>
  );
}

async function StrainCards() {
  const ids = STRAIN_CARDS.map((c) => c.metricId);
  const seriesMap = await safeSeriesMany(ids, "7d");

  return (
    <div className="activity-grid">
      {STRAIN_CARDS.map((card) => {
        const series = seriesMap.get(card.metricId) ?? null;
        const points = series?.points ?? [];
        const { latest: lastObs, average: avg } = summarizeNumericSeries(points);
        const fresh = lastObs ? agoLabel(lastObs.t) : "no data";

        return (
          <article key={card.metricId} className={`card activity-card${card.tone === "warn" ? " activity-tone-warn" : ""}`}>
            <div className="activity-card-head">
              <span className="activity-card-icon" aria-hidden>{card.icon}</span>
              <h2>{card.title}</h2>
            </div>
            <div className="activity-card-value">
              {lastObs ? (
                <>
                  <span className="activity-big">
                    <CountUp value={Math.round(lastObs.value)} />
                  </span>
                  <span className="activity-unit">{card.unit}</span>
                </>
              ) : (
                <span className="activity-big muted">—</span>
              )}
            </div>
            <div className="activity-card-foot mono">
              {avg !== null ? (
                <span>
                  7d avg <strong>{numberLabel(avg)}</strong> {card.unit}
                </span>
              ) : (
                <span>no readings in 7d</span>
              )}
              <span className="activity-fresh">{fresh}</span>
            </div>
          </article>
        );
      })}
    </div>
  );
}

async function StepsTimeline() {
  // Fetch steps at 30d directly. StrainCards requests steps at 7d via
  // safeSeriesMany — that's a separate purpose (grid card) and different
  // cache key. The process-level SWR cache means the upstream API only
  // pays once for the overlapping window; no duplicate network cost.
  const series = await safeSeries("activity.steps", "30d");
  if (!series || series.points.length < 3) return null;
  const values = series.points
    .filter((p): p is typeof p & { value: number } => p.value !== null)
    .map((p) => p.value);
  const hoverLabels = series.points
    .filter((p) => p.value !== null)
    .map((p) => new Date(p.t).toLocaleDateString(undefined, { month: "short", day: "numeric" }));

  return (
    <section className="lead">
      <article className="card">
        <h2>30-day steps</h2>
        <BaselineRibbon
          values={values}
          height={132}
          axis={["30 days ago", "today"]}
          hoverLabels={hoverLabels}
          unit="steps"
          ariaLabel="Steps over the last 30 days against your personal baseline"
        />
      </article>
    </section>
  );
}

async function WeeklyStrain() {
  const [rhrSeries, walkHrSeries] = await Promise.all([
    safeSeries("vital.resting_heart_rate", "30d"),
    safeSeries("vital.walking_heart_rate_average", "30d"),
  ]);

  const rhrVals = rhrSeries?.points.filter((p): p is typeof p & { value: number } => p.value !== null) ?? [];
  const walkHrVals = walkHrSeries?.points.filter((p): p is typeof p & { value: number } => p.value !== null) ?? [];

  const rhrAvg = rhrVals.length > 0 ? rhrVals.reduce((a, p) => a + p.value, 0) / rhrVals.length : null;
  const walkAvg = walkHrVals.length > 0 ? walkHrVals.reduce((a, p) => a + p.value, 0) / walkHrVals.length : null;

  // ── Cardiovascular load (strain) ────────────────────────────────────────
  //
  // Formula: strain = (walkingHR − restingHR) / restingHR × 100
  //
  // This is a simple proxy for cardiovascular strain. A healthy adult at rest
  // has a narrow gap (10-25%); a wider gap (30-40%+) indicates the heart is
  // working harder during daily movement. The absolute number matters less than
  // the week-over-week trend — rising strain with no change in routine can
  // signal overtraining, stress, or illness onset.
  //
  // Assumptions:
  //  • Walking HR is a representative sub-maximal load. A true strain model
  //    would incorporate max HR, HR reserve, METs, and training impulse (TRIMP).
  //  • Resting HR is the floor. In practice, Apple Watch resting HR is a daily
  //    summary (not truly basal), but it's the best available floor.
  //  • 30-day window smooths daily noise. A 7-day window is more responsive
  //    but noisier; the 30-day avg trades latency for stability.
  //
  // TODO(calibration): population-norm tuning. A 25% threshold for "elevated"
  //   is a heuristic. With enough population data, this threshold can be
  //   calibrated against age, sex, fitness level, and HRV.
  const strain = rhrAvg && walkAvg ? Math.round(((walkAvg - rhrAvg) / rhrAvg) * 100) : null;

  return (
    <section className="lead">
      <article className="card activity-strain-card">
        <h2>Cardiovascular load</h2>
        <p className="activity-strain-desc">
          The gap between your resting and walking heart rate estimates how hard your
          cardiovascular system worked this month. A wider gap means higher strain.
        </p>
        {strain !== null ? (
          <div className={`activity-strain-value ${strain > 25 ? "up" : ""}`}>
            <strong>+{strain}%</strong>
            <span>walking HR above resting</span>
          </div>
        ) : (
          <p className="empty">Not enough heart rate data for a strain estimate.</p>
        )}
        <div className="activity-strain-meta mono">
          {rhrAvg ? <span>Resting avg: {Math.round(rhrAvg)} bpm</span> : null}
          {walkAvg ? <span>Walking avg: {Math.round(walkAvg)} bpm</span> : null}
        </div>
      </article>
    </section>
  );
}

async function ActivityIntroNote() {
  const ids = STRAIN_CARDS.map((c) => c.metricId);
  const seriesMap = await safeSeriesMany(ids, "7d");
  const anyData = [...seriesMap.values()].some(
    (s) => s?.points.some((p) => p.value !== null && Number.isFinite(p.value)),
  );
  if (anyData) return null;
  return (
    <section className="route-note">
      <p>
        Steps and exercise minutes come from Apple Health. Sync from the HealthSave app to see your
        daily strain.{" "}
        <a href="/demo" style={{ color: "var(--accent)", fontWeight: 500 }}>
          Explore demo →
        </a>
      </p>
    </section>
  );
}

export default function ActivityPage() {
  return (
    <div className="activity-page">
      <Suspense fallback={null}>
        <ActivityIntroNote />
      </Suspense>

      <Suspense fallback={<CardSkeleton />}>
        <WeeklyStrain />
      </Suspense>

      <Suspense fallback={<CardSkeleton />}>
        <StepsTimeline />
      </Suspense>

      {/* How to read this */}
      <section className="lead">
        <article className="card">
          <h2>How to read this</h2>
          <div className="activity-notes">
            <div className="activity-note">
              <strong>Steps.</strong> Your daily step count from Apple Health. 7,000–10,000/day is a solid baseline for most adults. The trend ribbon shows whether you&apos;re moving more or less than usual.
            </div>
            <div className="activity-note">
              <strong>Exercise minutes.</strong> Apple Watch records this automatically when your heart rate indicates moderate activity. 150 minutes/week is the WHO guideline — the card shows your daily contribution.
            </div>
            <div className="activity-note">
              <strong>Resting heart rate.</strong> Lower is generally better (a fit heart pumps more blood per beat). A sustained rise can signal overtraining, stress, or illness — the ribbon catches those shifts.
            </div>
            <div className="activity-note">
              <strong>Walking heart rate.</strong> Your heart rate during a typical walk. A drop over time means you&apos;re getting fitter (less effort for the same walk). A sudden rise is worth watching.
            </div>
            <div className="activity-note">
              <strong>Cardiovascular load.</strong> The percentage gap between walking HR and resting HR. A wider gap means your heart works harder during daily activity. Trends show fitness changes — the absolute number matters less than the direction over weeks.
            </div>
          </div>
        </article>
      </section>
    </div>
  );
}
