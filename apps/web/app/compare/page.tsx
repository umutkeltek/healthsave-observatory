import type { Metadata } from "next";

import { CompareControls } from "../components/CompareControls";
import { ComparisonCard, type Side } from "../components/ComparisonCard";
import { MultiSeriesChart, type ChartSeries } from "../components/MultiSeriesChart";
import { type Delta, groupBySource, groupByStream, periodSplit } from "../lib/analytics";
import type { MetricSeries, SeriesPoint, StreamView } from "../lib/api";
import { DEMO_COMPARE_SERIES } from "../lib/demoSeries";
import { comparability } from "../lib/healthOpinion";
import { safeMetrics, safeSeries, safeStreams } from "../lib/load";

export const metadata: Metadata = { title: "Compare · HealthSave" };
export const dynamic = "force-dynamic";

const RANGES = ["7d", "30d", "90d", "1y"];

type SearchParams = { [key: string]: string | string[] | undefined };
const one = (v: string | string[] | undefined): string => (Array.isArray(v) ? (v[0] ?? "") : (v ?? ""));
const round1 = (n: number): number => Number(n.toFixed(1));
const byTime = (a: SeriesPoint, b: SeriesPoint): number => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0);
function vals(points: SeriesPoint[]): number[] {
  return points.map((p) => p.value).filter((v): v is number => v !== null);
}
function mean(values: number[]): number {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
}

type CardModel = { a: Side; b: Side; delta: Delta; caveat: string | null; warn: boolean };

// A device stream's human label — the registry's device_label, or a tidied
// fallback from the stream id so demo/unknown streams still read sensibly.
function streamLabel(id: string, labels: Map<string, string>): string {
  const known = labels.get(id);
  if (known) return known;
  const tidy = id.replace(/^demo-/, "").replace(/-/g, " ").trim();
  return tidy ? tidy.replace(/\b\w/g, (c) => c.toUpperCase()) : id;
}

export default async function ComparePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const metricSel = one(sp.metric);
  const modeSel = one(sp.mode);
  const mode = modeSel === "source" || modeSel === "device" ? modeSel : "period";
  const range = RANGES.includes(one(sp.range)) ? one(sp.range) : "30d";

  const [metrics, streams] = await Promise.all([safeMetrics(), safeStreams()]);
  const all = metrics ?? [];
  const metricId = metricSel || all[0]?.id || DEMO_COMPARE_SERIES.metric.id;
  const streamLabels = new Map<string, string>(
    (streams ?? []).map((s: StreamView) => [s.id, s.device_label ?? s.source_plugin_id]),
  );

  const live = await safeSeries(metricId, range);
  const isDemo = live === null;
  const series: MetricSeries = live ?? DEMO_COMPARE_SERIES;
  const unit = series.metric.canonical_unit ?? "";

  let chart: ChartSeries[] = [];
  let card: CardModel | null = null;
  let note: string | null = null;

  if (mode === "device") {
    const groups = [...groupByStream(series.points).entries()]
      .map(([id, pts]) => ({ id, label: streamLabel(id, streamLabels), pts: [...pts].sort(byTime) }))
      .sort((a, b) => b.pts.length - a.pts.length);
    chart = groups.slice(0, 4).map((g) => ({ label: g.label, values: vals(g.pts) }));
    if (groups.length < 2) {
      note = "Only one device stream for this metric — connect another device to compare.";
    } else {
      const [A, B] = groups;
      const ma = mean(vals(A.pts));
      const mb = mean(vals(B.pts));
      const abs = round1(mb - ma);
      const pct = ma !== 0 ? Number(((abs / Math.abs(ma)) * 100).toFixed(1)) : null;
      const cmp = comparability(metricId, [A.label, B.label]);
      card = {
        a: { label: A.label, value: round1(ma), meta: `${vals(A.pts).length} readings` },
        b: { label: B.label, value: round1(mb), meta: `${vals(B.pts).length} readings` },
        delta: { abs, pct, direction: abs > 0 ? "up" : abs < 0 ? "down" : "flat" },
        caveat: cmp.caveat,
        warn: cmp.warn,
      };
    }
  } else if (mode === "source") {
    const groups = [...groupBySource(series.points).entries()]
      .map(([source, pts]) => ({ source, pts: [...pts].sort(byTime) }))
      .sort((a, b) => b.pts.length - a.pts.length);
    chart = groups.slice(0, 4).map((g) => ({ label: g.source, values: vals(g.pts) }));
    if (groups.length < 2) {
      note = "Only one source for this metric — connect another source to compare.";
    } else {
      const [A, B] = groups;
      const ma = mean(vals(A.pts));
      const mb = mean(vals(B.pts));
      const abs = round1(mb - ma);
      const pct = ma !== 0 ? Number(((abs / Math.abs(ma)) * 100).toFixed(1)) : null;
      const cmp = comparability(metricId, [A.source, B.source]);
      card = {
        a: { label: A.source, value: round1(ma), meta: `${vals(A.pts).length} readings` },
        b: { label: B.source, value: round1(mb), meta: `${vals(B.pts).length} readings` },
        delta: { abs, pct, direction: abs > 0 ? "up" : abs < 0 ? "down" : "flat" },
        caveat: cmp.caveat,
        warn: cmp.warn,
      };
    }
  } else {
    const sorted = [...series.points].filter((p) => p.value !== null).sort(byTime);
    const mid = Math.floor(sorted.length / 2);
    chart = [
      { label: "Earlier", values: vals(sorted.slice(0, mid)) },
      { label: "Later", values: vals(sorted.slice(mid)) },
    ];
    const ps = periodSplit(series.points);
    const cmp = comparability(metricId, [...new Set(series.points.map((p) => p.source_id))]);
    card = {
      a: { label: "Earlier", value: round1(ps.a.mean), meta: `${ps.a.n} readings` },
      b: { label: "Later", value: round1(ps.b.mean), meta: `${ps.b.n} readings` },
      delta: { abs: round1(ps.delta.abs), pct: ps.delta.pct, direction: ps.delta.direction },
      caveat: cmp.warn ? cmp.caveat : null,
      warn: cmp.warn,
    };
  }

  const controlMetrics = all.length
    ? all.map((m) => ({ id: m.id, display_name: m.display_name, category: m.category }))
    : [{ id: series.metric.id, display_name: series.metric.display_name, category: series.metric.category }];

  return (
    <>
      <div className="prov-intro">
        <h2>Compare</h2>
        <p>
          Period vs previous, or source vs source — both readings are kept, never merged into one number.
          The gap is the signal, not a blended figure.
        </p>
      </div>

      <CompareControls metrics={controlMetrics} ranges={RANGES} />

      <section className="lead">
        <article className="card">
          <div className="card-title">
            {series.metric.display_name}
            {isDemo ? " · demo" : ` · ${range}`}
          </div>
          <MultiSeriesChart series={chart} />
        </article>
      </section>

      {card && (
        <section className="lead">
          <ComparisonCard
            title={
              mode === "device"
                ? "Device vs device"
                : mode === "source"
                  ? "Source vs source"
                  : "Period vs previous"
            }
            unit={unit}
            a={card.a}
            b={card.b}
            delta={card.delta}
            caveat={card.caveat}
            warn={card.warn}
          />
        </section>
      )}
      {note && (
        <section className="lead">
          <article className="card">
            <p className="empty">{note}</p>
          </article>
        </section>
      )}

      <footer className="foot">
        {isDemo
          ? "demo data · illustrative comparison · nothing left this host"
          : `${series.metric.id} · ${range} · nothing left this host`}
      </footer>
    </>
  );
}
