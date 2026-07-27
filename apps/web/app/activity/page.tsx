import type { Metadata } from "next";
import { Suspense } from "react";

import { BaselineRibbon } from "../components/BaselineRibbon";
import { CountUp } from "../components/CountUp";
import { CardSkeleton } from "../components/Skeletons";
import { agoLabel, safeSeries, safeSeriesMany } from "../lib/load";

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
        const numeric = points.filter((p): p is typeof p & { value: number } => p.value !== null);
        const sorted = [...numeric].map((p) => p.value).sort((a, b) => a - b);
        const latest = sorted.at(-1);
        const avg = sorted.length > 0 ? sorted.reduce((a, b) => a + b, 0) / sorted.length : null;
        const lastObs = numeric.at(-1);
        const fresh = lastObs ? agoLabel(lastObs.t) : "no data";

        return (
          <article key={card.metricId} className={`card activity-card ${card.tone ?? ""}`}>
            <div className="activity-card-head">
              <span className="activity-card-icon" aria-hidden>{card.icon}</span>
              <h2>{card.title}</h2>
            </div>
            <div className="activity-card-value">
              {latest !== undefined ? (
                <>
                  <span className="activity-big">
                    <CountUp value={Math.round(latest)} />
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
  const [hrSeries, walkHrSeries] = await Promise.all([
    safeSeries("vital.heart_rate", "30d"),
    safeSeries("vital.walking_heart_rate_average", "30d"),
  ]);

  const hrVals = hrSeries?.points.filter((p): p is typeof p & { value: number } => p.value !== null) ?? [];
  const walkHrVals = walkHrSeries?.points.filter((p): p is typeof p & { value: number } => p.value !== null) ?? [];

  const hrAvg = hrVals.length > 0 ? hrVals.reduce((a, p) => a + p.value, 0) / hrVals.length : null;
  const walkAvg = walkHrVals.length > 0 ? walkHrVals.reduce((a, p) => a + p.value, 0) / walkHrVals.length : null;

  // Simple strain proxy: walking HR vs resting delta. Higher = more strain.
  const strain = hrAvg && walkAvg ? Math.round(((walkAvg - hrAvg) / hrAvg) * 100) : null;

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
          {hrAvg ? <span>Resting avg: {Math.round(hrAvg)} bpm</span> : null}
          {walkAvg ? <span>Walking avg: {Math.round(walkAvg)} bpm</span> : null}
        </div>
      </article>
    </section>
  );
}

export default function ActivityPage() {
  return (
    <div className="activity-page">
      <Suspense fallback={<StrainSectionFallback />}>
        <StrainCards />
      </Suspense>

      <Suspense fallback={<CardSkeleton />}>
        <WeeklyStrain />
      </Suspense>

      <Suspense fallback={<CardSkeleton />}>
        <StepsTimeline />
      </Suspense>
    </div>
  );
}
