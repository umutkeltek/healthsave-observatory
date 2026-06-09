import type { Metadata } from "next";

import { FilterBar } from "../components/FilterBar";
import { MetricCard } from "../components/MetricCard";
import { ReadinessCard } from "../components/ReadinessCard";
import { SleepCard } from "../components/SleepCard";
import { SourceDistribution } from "../components/SourceDistribution";
import { distribution } from "../lib/analytics";
import type { MetricSeries, MetricSummary } from "../lib/api";
import { GRID_METRICS, loadReadinessSparklines, safeMetrics, safeReadiness, safeSeries } from "../lib/load";

export const metadata: Metadata = { title: "Data · HealthSave" };
export const dynamic = "force-dynamic";

const RANGES = ["24h", "7d", "30d", "90d", "1y"];
// N+1 guard: never fetch more than this many series in one render. The default
// (unfiltered) grid uses the smaller ceiling; an explicit category filter may
// show a few more, but stays bounded.
const DEFAULT_CAP = 8;
const FILTERED_CAP = 12;

type SearchParams = { [key: string]: string | string[] | undefined };
function one(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

type Card = { metric: MetricSummary; series: MetricSeries | null };

// Sort the visible cards by the chosen key, derived from each series.
function sortCards(cards: Card[], sort: string): Card[] {
  if (sort === "name") {
    return [...cards].sort((a, b) => a.metric.display_name.localeCompare(b.metric.display_name));
  }
  const lastValue = (c: Card): number => {
    const vals = (c.series?.points ?? []).map((p) => p.value).filter((v): v is number => v !== null);
    if (sort === "coverage") return vals.length;
    return vals.at(-1) ?? Number.NEGATIVE_INFINITY; // "recent"
  };
  if (sort === "recent" || sort === "coverage") {
    return [...cards].sort((a, b) => lastValue(b) - lastValue(a));
  }
  return cards; // default order
}

export default async function DataPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const metricSel = one(sp.metric);
  const categorySel = one(sp.category);
  const sourceSel = one(sp.source);
  const sortSel = one(sp.sort);
  const range = RANGES.includes(one(sp.range)) ? one(sp.range) : "7d";

  const [readiness, metrics] = await Promise.all([safeReadiness(), safeMetrics()]);
  const all = metrics ?? [];
  const categories = [...new Set(all.map((m) => m.category).filter(Boolean))].sort();

  // Default grid, also the fallback when the backend is unreachable (so the
  // page still renders the familiar cards in their graceful empty state).
  const fallback: MetricSummary[] = GRID_METRICS.map((g) => ({
    id: g.id,
    display_name: g.title,
    category: "",
    value_type: "",
    canonical_unit: null,
  }));

  // Resolve the visible metric set from the active filters, bounded to guard N+1.
  let visible: MetricSummary[];
  if (all.length === 0) {
    visible = fallback;
  } else if (metricSel) {
    visible = all.filter((m) => m.id === metricSel);
  } else if (categorySel) {
    visible = all.filter((m) => m.category === categorySel).slice(0, FILTERED_CAP);
  } else {
    const byId = new Map(all.map((m) => [m.id, m]));
    const defaults = GRID_METRICS.map((g) => byId.get(g.id)).filter((m): m is MetricSummary => Boolean(m));
    visible = (defaults.length ? defaults : all).slice(0, DEFAULT_CAP);
  }
  const isDefault = !metricSel && !categorySel;

  const [sparklines, seriesList, sleep] = await Promise.all([
    loadReadinessSparklines(readiness),
    Promise.all(visible.map((m) => safeSeries(m.id, range))),
    isDefault ? safeSeries("sleep.stage", range) : Promise.resolve(null),
  ]);

  // Source facet + distribution from the actually-fetched points.
  const allPoints = seriesList.flatMap((s) => s?.points ?? []);
  const sources = [...new Set(allPoints.map((p) => p.source_id))].sort();
  const dist = distribution(sourceSel ? allPoints.filter((p) => p.source_id === sourceSel) : allPoints);

  // Apply the source filter to each series client-side, then sort.
  const cards = sortCards(
    visible.map((metric, i) => {
      const series = seriesList[i];
      const filtered =
        series && sourceSel ? { ...series, points: series.points.filter((p) => p.source_id === sourceSel) } : series;
      return { metric, series: filtered };
    }),
    sortSel,
  );

  return (
    <>
      <section className="lead">
        <ReadinessCard readiness={readiness} sparklines={sparklines} />
      </section>

      <FilterBar
        metrics={(all.length ? all : fallback).map((m) => ({
          id: m.id,
          display_name: m.display_name,
          category: m.category,
        }))}
        categories={categories}
        sources={sources}
        ranges={RANGES}
      />

      <SourceDistribution dist={dist} />

      <div className="section-label">
        {metrics === null
          ? "Metrics"
          : `${visible.length} metric${visible.length === 1 ? "" : "s"} · ${range}${sourceSel ? ` · ${sourceSel}` : ""}`}
      </div>
      <section className="grid">
        {cards.map(({ metric, series }) => (
          <MetricCard key={metric.id} series={series} fallbackTitle={metric.display_name} />
        ))}
        {isDefault && <SleepCard series={sleep} />}
      </section>
    </>
  );
}
