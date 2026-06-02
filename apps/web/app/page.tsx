import { EvidenceCard } from "./components/EvidenceCard";
import { ExperimentsCard } from "./components/ExperimentsCard";
import { MetricCard } from "./components/MetricCard";
import { PrivacyCard } from "./components/PrivacyCard";
import { ReadinessCard } from "./components/ReadinessCard";
import { SleepCard } from "./components/SleepCard";
import { WeeklyBriefCard } from "./components/WeeklyBriefCard";
import {
  GRID_METRICS,
  loadGrid,
  safeCandidates,
  safeExperiments,
  safeFindings,
  safeLatest,
  safePrivacy,
  safeReadiness,
  safeSeries,
} from "./lib/load";

// Always render fresh — this is a live dashboard, not a static page.
export const dynamic = "force-dynamic";

export default async function Home() {
  const [readiness, latest, findings, candidates, experiments, privacy, sleep, gridSeries] =
    await Promise.all([
      safeReadiness(),
      safeLatest(),
      safeFindings(),
      safeCandidates(),
      safeExperiments(),
      safePrivacy(),
      safeSeries("sleep.stage", "7d"),
      loadGrid(),
    ]);

  return (
    <>
      <section className="lead">
        <ReadinessCard readiness={readiness} />
      </section>

      <div className="row-2">
        <WeeklyBriefCard latest={latest} />
        <PrivacyCard privacy={privacy} />
      </div>

      <section className="lead">
        <EvidenceCard findings={findings} />
      </section>

      <section className="lead">
        <ExperimentsCard experiments={experiments} candidates={candidates} />
      </section>

      <div className="section-label">Metrics</div>
      <section className="grid">
        {GRID_METRICS.map((metric, index) => (
          <MetricCard key={metric.id} series={gridSeries[index]} fallbackTitle={metric.title} />
        ))}
        <SleepCard series={sleep} />
      </section>

      <footer className="foot">datahub v2 · canonical observations · insight-first</footer>
    </>
  );
}
