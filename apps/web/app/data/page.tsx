import { MetricCard } from "../components/MetricCard";
import { ReadinessCard } from "../components/ReadinessCard";
import { SleepCard } from "../components/SleepCard";
import { GRID_METRICS, loadGrid, safeReadiness, safeSeries } from "../lib/load";

export const dynamic = "force-dynamic";

export default async function DataPage() {
  const [readiness, sleep, gridSeries] = await Promise.all([
    safeReadiness(),
    safeSeries("sleep.stage", "7d"),
    loadGrid(),
  ]);
  return (
    <>
      <section className="lead">
        <ReadinessCard readiness={readiness} />
      </section>
      <div className="section-label">Metrics</div>
      <section className="grid">
        {GRID_METRICS.map((metric, index) => (
          <MetricCard key={metric.id} series={gridSeries[index]} fallbackTitle={metric.title} />
        ))}
        <SleepCard series={sleep} />
      </section>
    </>
  );
}
