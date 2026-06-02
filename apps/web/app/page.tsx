import { MetricCard } from "./components/MetricCard";
import { ReadinessCard } from "./components/ReadinessCard";
import { SleepCard } from "./components/SleepCard";
import { fetchReadiness, fetchSeries, type MetricSeries, type Readiness } from "./lib/api";

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

export default async function Home() {
  const [readiness, heartRate, sleep] = await Promise.all([
    safeReadiness(),
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

      <section className="grid">
        <MetricCard series={heartRate} fallbackTitle="Heart Rate" />
        <SleepCard series={sleep} />
      </section>

      <footer className="foot">datahub v2 · canonical observations · insight-first</footer>
    </main>
  );
}
