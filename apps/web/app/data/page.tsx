import type { Metadata } from "next";

import { DataTable } from "../components/DataTable";
import { DayOfWeekChart } from "../components/DayOfWeekChart";
import { ExportCard } from "../components/ExportCard";
import { FilterBar } from "../components/FilterBar";
import { HeatmapChart } from "../components/HeatmapChart";
import { MetricCard } from "../components/MetricCard";
import { ReadinessCard } from "../components/ReadinessCard";
import { SleepCard } from "../components/SleepCard";
import { SourceDistribution } from "../components/SourceDistribution";
import { ZoneBar } from "../components/ZoneBar";
import { dayOfWeekPivot, distribution, hrZoneHistogram, weekHourPivot } from "../lib/analytics";
import type { MetricSeries, MetricSummary, SeriesPoint } from "../lib/api";
import { demoPatternSeries } from "../lib/demoSeries";
import {
  GRID_METRICS,
  loadReadinessSparklines,
  safeExportMetrics,
  safeMetrics,
  safeReadiness,
  safeSeries,
  safeStreams,
} from "../lib/load";

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
  const deviceSel = one(sp.device);
  const sortSel = one(sp.sort);
  const range = RANGES.includes(one(sp.range)) ? one(sp.range) : "7d";

  const [readiness, metrics, streams, exportMetrics] = await Promise.all([
    safeReadiness(),
    safeMetrics(),
    safeStreams(),
    safeExportMetrics(),
  ]);
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

  // Source + device facets from the actually-fetched points.
  const allPoints = seriesList.flatMap((s) => s?.points ?? []);
  const sources = [...new Set(allPoints.map((p) => p.source_id))].sort();
  const streamLabels = new Map((streams ?? []).map((s) => [s.id, s.device_label ?? s.source_plugin_id]));
  const deviceIds = [...new Set(allPoints.map((p) => p.stream_id).filter((s): s is string => Boolean(s)))];
  const devices = deviceIds
    .map((id) => ({ id, label: streamLabels.get(id) ?? id }))
    .sort((a, b) => a.label.localeCompare(b.label));

  const keep = (p: SeriesPoint): boolean =>
    (!sourceSel || p.source_id === sourceSel) && (!deviceSel || p.stream_id === deviceSel);
  const filtering = Boolean(sourceSel || deviceSel);

  const dist = distribution(allPoints.filter(keep));

  // Apply the source/device filter to each series client-side, then sort.
  const cards = sortCards(
    visible.map((metric, i) => {
      const series = seriesList[i];
      const filtered = series && filtering ? { ...series, points: series.points.filter(keep) } : series;
      return { metric, series: filtered };
    }),
    sortSel,
  );

  // Patterns panels for a single selected metric (exotic Grafana panels,
  // computed from its series points). Falls back to a labelled demo offline.
  const selectedMetric: MetricSummary | null = metricSel
    ? (all.find((m) => m.id === metricSel) ??
      fallback.find((m) => m.id === metricSel) ?? {
        id: metricSel,
        display_name: metricSel.split(".").pop() ?? metricSel,
        category: "",
        value_type: "",
        canonical_unit: null,
      })
    : null;

  let patterns: { metric: MetricSummary; points: SeriesPoint[]; unit: string; isHr: boolean; demo: boolean } | null =
    null;
  if (selectedMetric) {
    const liveSeries = cards.length === 1 && cards[0].metric.id === metricSel ? cards[0].series : null;
    const demo = (liveSeries?.points.length ?? 0) === 0;
    const src = demo ? demoPatternSeries(selectedMetric) : (liveSeries as MetricSeries);
    patterns = {
      metric: selectedMetric,
      points: src.points,
      unit: src.metric.canonical_unit ?? "",
      isHr: selectedMetric.id.includes("heart_rate") || src.metric.canonical_unit === "bpm",
      demo,
    };
  }

  return (
    <>
      <FilterBar
        metrics={(all.length ? all : fallback).map((m) => ({
          id: m.id,
          display_name: m.display_name,
          category: m.category,
        }))}
        categories={categories}
        sources={sources}
        devices={devices}
        ranges={RANGES}
      />

      <SourceDistribution dist={dist} />

      <div className="section-label">
        {metrics === null
          ? "Metrics"
          : `${visible.length} metric${visible.length === 1 ? "" : "s"} · ${range}${sourceSel ? ` · ${sourceSel}` : ""}${deviceSel ? ` · ${streamLabels.get(deviceSel) ?? deviceSel}` : ""}`}
      </div>
      <section className="grid">
        {cards.map(({ metric, series }) => (
          <MetricCard key={metric.id} series={series} fallbackTitle={metric.display_name} />
        ))}
        {isDefault && <SleepCard series={sleep} />}
      </section>

      {patterns && (
        <>
          <div className="section-label">
            Patterns · {patterns.metric.display_name}
            {patterns.demo ? " · demo" : ""}
          </div>
          <div className="today-grid prov-grid">
            <article className="card col-8">
              <div className="card-title">When in the week</div>
              <HeatmapChart cells={weekHourPivot(patterns.points)} unit={patterns.unit} />
            </article>
            <article className="card col-4">
              <div className="card-title">By weekday</div>
              <DayOfWeekChart cells={dayOfWeekPivot(patterns.points)} unit={patterns.unit} />
            </article>
            {patterns.isHr && (
              <article className="card col-12">
                <div className="card-title">Heart-rate zones</div>
                <ZoneBar zones={hrZoneHistogram(patterns.points)} />
              </article>
            )}
            <article className="card col-12">
              <div className="card-title">Recent readings</div>
              <DataTable points={patterns.points} unit={patterns.unit} />
            </article>
          </div>
        </>
      )}

      <div className="section-label" style={{ marginTop: 36 }}>
        Data readiness
      </div>
      <section className="lead">
        <ReadinessCard readiness={readiness} sparklines={sparklines} />
      </section>

      <div className="section-label" style={{ marginTop: 36 }}>
        Take it with you
      </div>
      <section className="lead">
        <ExportCard metrics={exportMetrics} />
      </section>
    </>
  );
}
