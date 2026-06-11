import type { Metadata } from "next";
import Link from "next/link";

import { MultiSeriesChart, type ChartSeries } from "../components/MultiSeriesChart";
import { RelateControls } from "../components/RelateControls";
import { RunCorrelationButton } from "../components/RunCorrelationButton";
import { ScatterChart } from "../components/ScatterChart";
import {
  type AlignedPair,
  alignDaily,
  CORRELATION_MIN_DAYS,
  pearson,
} from "../lib/analytics";
import type { Correlation, MetricSeries, MetricSummary } from "../lib/api";
import { DEMO_CORRELATIONS, DEMO_RELATE_METRICS, demoRelatedPair } from "../lib/demoSeries";
import { agoLabel, safeCorrelations, safeMetrics, safeSeries } from "../lib/load";

export const metadata: Metadata = { title: "Relationships · HealthSave" };
export const dynamic = "force-dynamic";

const RANGES = ["30d", "90d", "1y"];
const ID_RE = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/;

type SearchParams = { [key: string]: string | string[] | undefined };
const one = (v: string | string[] | undefined): string => (Array.isArray(v) ? (v[0] ?? "") : (v ?? ""));

// Display name from the catalog, else a prettified metric-id tail (the
// /compare fallback idiom) — never a raw dotted id in running copy.
function prettyName(catalog: MetricSummary[], id: string): string {
  const hit = catalog.find((m) => m.id === id);
  if (hit) return hit.display_name;
  const tidy = id.split(".").pop()?.replace(/_/g, " ").trim() ?? "";
  return tidy ? tidy.replace(/\b\w/g, (c) => c.toUpperCase()) : id;
}

function unitOf(catalog: MetricSummary[], id: string, series: MetricSeries | null): string {
  const unit = series?.metric.canonical_unit ?? catalog.find((m) => m.id === id)?.canonical_unit;
  return unit ? ` (${unit})` : "";
}

// Normalize one side of the pair to its own 0–1 range for the overlay chart.
// Shapes stay comparable; magnitudes are deliberately NOT comparable and the
// caption says so.
function ownScale(values: number[]): number[] {
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  return values.map((v) => Number(((v - min) / span).toFixed(4)));
}

function CorrelationRow({
  row,
  catalog,
  range,
}: {
  row: Correlation;
  catalog: MetricSummary[];
  range: string;
}) {
  const a = row.metric_a ?? "";
  const b = row.metric_b ?? "";
  const r = row.coefficient;
  const significant = row.p_value !== null && row.p_value < 0.05;
  const width = r === null ? 0 : Math.min(100, Math.round(Math.abs(r) * 100));
  return (
    <tr>
      <td>
        <Link
          className="rel-pair"
          href={`/relationships?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&range=${range}`}
        >
          {prettyName(catalog, a)} <span className="rel-x" aria-hidden>×</span> {prettyName(catalog, b)}
        </Link>
      </td>
      <td className="rel-r mono">
        <span className={`rel-bar ${r !== null && r < 0 ? "neg" : ""}`} aria-hidden>
          <span style={{ width: `${width}%` }} />
        </span>
        {r === null ? "—" : r.toFixed(2)}
      </td>
      <td className="mono">{row.method ?? "—"}</td>
      <td className="mono">
        {row.p_value === null ? "—" : `p=${row.p_value.toFixed(3)}`}
        {row.p_value !== null && !significant && <span className="rel-weak"> · weak</span>}
      </td>
      <td className="mono">{row.period_days ? `${row.period_days}d` : "—"}</td>
      <td className="mono">{agoLabel(row.created_at)}</td>
    </tr>
  );
}

export default async function RelationshipsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const range = RANGES.includes(one(sp.range)) ? one(sp.range) : "90d";
  const aId = ID_RE.test(one(sp.a)) ? one(sp.a) : "";
  const bId = ID_RE.test(one(sp.b)) ? one(sp.b) : "";

  const [metrics, correlations] = await Promise.all([safeMetrics(), safeCorrelations()]);
  // Both reads failed ⇒ backend unreachable ⇒ clearly-labelled demo (the
  // fresh-clone idiom). A reachable backend with zero correlations is a
  // DIFFERENT state: honest empty + the compute button.
  const unreachable = metrics === null && correlations === null;
  const rows = unreachable ? DEMO_CORRELATIONS : (correlations ?? []);
  const catalog = metrics ?? DEMO_RELATE_METRICS;

  // Pair series: live when reachable, the coupled demo pair when not.
  let seriesA: MetricSeries | null = null;
  let seriesB: MetricSeries | null = null;
  const pairChosen = Boolean(aId && bId && aId !== bId);
  if (pairChosen) {
    if (unreachable) {
      const summary = (id: string): MetricSummary =>
        catalog.find((m) => m.id === id) ?? {
          id,
          display_name: prettyName(catalog, id),
          category: id.split(".")[0] ?? "",
          value_type: "numeric",
          canonical_unit: null,
        };
      ({ a: seriesA, b: seriesB } = demoRelatedPair(summary(aId), summary(bId)));
    } else {
      [seriesA, seriesB] = await Promise.all([safeSeries(aId, range), safeSeries(bId, range)]);
    }
  }

  const pairs: AlignedPair[] = seriesA && seriesB ? alignDaily(seriesA.points, seriesB.points) : [];
  const stat = pearson(pairs);
  const nameA = aId ? prettyName(catalog, aId) : "";
  const nameB = bId ? prettyName(catalog, bId) : "";
  const overlay: ChartSeries[] =
    pairs.length >= 2
      ? [
          { label: nameA, values: ownScale(pairs.map((p) => p.a)) },
          { label: nameB, values: ownScale(pairs.map((p) => p.b)) },
        ]
      : [];

  const options = catalog
    .map((m) => ({ id: m.id, display_name: m.display_name, category: m.category }))
    .sort((x, y) => x.display_name.localeCompare(y.display_name));

  return (
    <>
      <section className="lead">
        <article className="card">
          <div className="rel-head">
            <h2>Computed relationships</h2>
            <RunCorrelationButton />
          </div>
          <p className="rel-sub">
            Cross-metric correlations the statistical engine computed and persisted — with method,
            p-value, and window. Click a pair to explore it below.
          </p>
          {rows.length === 0 ? (
            <p className="empty">
              No correlations computed yet — they appear once the engine runs over enough paired
              days. Use “Compute now”, or pick a pair below to explore directly.
            </p>
          ) : (
            <div className="prov-scroll">
              <table className="prov datatable rel-table">
                <thead>
                  <tr>
                    <th>Pair</th>
                    <th>r</th>
                    <th>Method</th>
                    <th>Significance</th>
                    <th>Window</th>
                    <th>Computed</th>
                  </tr>
                </thead>
                <tbody>
                  {rows
                    .filter((row) => row.metric_a && row.metric_b)
                    .map((row, i) => (
                      <CorrelationRow
                        key={`${row.metric_a}-${row.metric_b}-${i}`}
                        row={row}
                        catalog={catalog}
                        range={range}
                      />
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>

      <section className="lead">
        <article className="card">
          <h2>Explore a pair</h2>
          <p className="rel-sub">
            Day means over shared days — both signals kept verbatim, each on its own scale.
          </p>
          <RelateControls metrics={options} ranges={RANGES} />

          {!pairChosen && aId && aId === bId && (
            <p className="empty">Pick two different signals.</p>
          )}
          {!pairChosen && !(aId && aId === bId) && (
            <p className="empty">Pick two signals — or click a computed pair above.</p>
          )}
          {pairChosen && (!seriesA || !seriesB) && (
            <p className="empty">Couldn’t load one of the series — try another pair or range.</p>
          )}
          {pairChosen && seriesA && seriesB && pairs.length < CORRELATION_MIN_DAYS && (
            <p className="empty">
              Only {pairs.length} shared day{pairs.length === 1 ? "" : "s"} in this range — at
              least {CORRELATION_MIN_DAYS} are needed before a coefficient means anything.
            </p>
          )}
          {pairChosen && seriesA && seriesB && pairs.length >= CORRELATION_MIN_DAYS && (
            <>
              <div className="rel-stat mono">
                r = {stat ? stat.r.toFixed(2) : "—"} · n = {pairs.length} shared days · exploratory
                (no p-value)
              </div>
              <MultiSeriesChart series={overlay} />
              <p className="rel-note">
                Each curve is scaled to its own range — compare shape and timing, not magnitude.
              </p>
              <ScatterChart
                pairs={pairs}
                xLabel={`${nameA}${unitOf(catalog, aId, seriesA)}`}
                yLabel={`${nameB}${unitOf(catalog, bId, seriesB)}`}
              />
            </>
          )}
        </article>
      </section>

      <footer className="foot">
        {unreachable
          ? "demo data · illustrative relationships · nothing left this host"
          : "correlation ≠ causation · computed on this host · nothing left this host"}
      </footer>
    </>
  );
}
