import { EvidenceCard } from "./components/EvidenceCard";
import { ExperimentsCard } from "./components/ExperimentsCard";
import { MetricCard } from "./components/MetricCard";
import { PrivacyCard } from "./components/PrivacyCard";
import { ReadinessCard } from "./components/ReadinessCard";
import { SleepCard } from "./components/SleepCard";
import { WeeklyBriefCard } from "./components/WeeklyBriefCard";
import {
  type Candidates,
  fetchCandidates,
  fetchFindings,
  fetchLatest,
  fetchPrivacy,
  fetchReadiness,
  fetchSeries,
  type Finding,
  type InsightsLatest,
  type MetricSeries,
  type Privacy,
  type Readiness,
} from "./lib/api";

// Always render fresh — this is a live dashboard, not a static page.
export const dynamic = "force-dynamic";

async function safeSeries(id: string, range = "7d"): Promise<MetricSeries | null> {
  try {
    return await fetchSeries(id, range);
  } catch {
    return null;
  }
}

async function safeReadiness(): Promise<Readiness | null> {
  try {
    return await fetchReadiness();
  } catch {
    return null;
  }
}

async function safeLatest(): Promise<InsightsLatest | null> {
  try {
    return await fetchLatest();
  } catch {
    return null;
  }
}

async function safeFindings(): Promise<Finding[] | null> {
  try {
    return (await fetchFindings()).findings;
  } catch {
    return null;
  }
}

async function safeCandidates(): Promise<Candidates | null> {
  try {
    return await fetchCandidates();
  } catch {
    return null;
  }
}

async function safePrivacy(): Promise<Privacy | null> {
  try {
    return await fetchPrivacy();
  } catch {
    return null;
  }
}

export default async function Home() {
  const [readiness, latest, findings, candidates, privacy, heartRate, sleep] = await Promise.all([
    safeReadiness(),
    safeLatest(),
    safeFindings(),
    safeCandidates(),
    safePrivacy(),
    safeSeries("vital.heart_rate", "7d"),
    safeSeries("sleep.stage", "7d"),
  ]);

  return (
    <main className="shell">
      <header className="masthead">
        <h1>HealthSave</h1>
        <p>Your data, interpreted — not just charted.</p>
      </header>

      <section className="lead">
        <ReadinessCard readiness={readiness} />
      </section>

      <section className="lead">
        <WeeklyBriefCard latest={latest} />
      </section>

      <section className="lead">
        <EvidenceCard findings={findings} />
      </section>

      <section className="lead">
        <ExperimentsCard candidates={candidates} />
      </section>

      <section className="lead">
        <PrivacyCard privacy={privacy} />
      </section>

      <section className="grid">
        <MetricCard series={heartRate} fallbackTitle="Heart Rate" />
        <SleepCard series={sleep} />
      </section>

      <footer className="foot">datahub v2 · canonical observations · insight-first</footer>
    </main>
  );
}
