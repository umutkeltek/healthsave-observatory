import type { Metadata } from "next";

import { MetricCard } from "../components/MetricCard";
import { ReadinessCard } from "../components/ReadinessCard";
import { SleepCard } from "../components/SleepCard";
import {
  GRID_METRICS,
  loadGrid,
  loadReadinessSparklines,
  safeReadiness,
  safeSeries,
} from "../lib/load";

export const metadata: Metadata = { title: "Data · HealthSave" };
export const dynamic = "force-dynamic";

export default async function DataPage() {
  const readiness = await safeReadiness();
  const [sleep, gridSeries, sparklines] = await Promise.all([
    safeSeries("sleep.stage", "7d"),
    loadGrid(),
    loadReadinessSparklines(readiness),
  ]);
  return (
    <>
      <section className="lead">
        <ReadinessCard readiness={readiness} sparklines={sparklines} />
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
