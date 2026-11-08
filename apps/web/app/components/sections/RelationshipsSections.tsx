// Relationships page sections - the computed-correlations table and the
// pair explorer stream independently. Shared reads (metrics catalog,
// correlations) are cache()-deduped in lib/load.ts, so both sections asking
// costs one upstream fetch per surface per request.

import Link from "next/link";

import { MultiSeriesChart, type ChartSeries } from "../MultiSeriesChart";
import { RelateControls } from "../RelateControls";
import { RunCorrelationButton } from "../RunCorrelationButton";
import { ScatterChart } from "../ScatterChart";
import { timeBasisLabel, UTC_TIME_BASIS } from "../../lib/analyticalTime";
import {
  type AlignedPair,
  alignDaily,
  CORRELATION_MIN_DAYS,
  pearson,
} from "../../lib/analytics";
import type { Correlation, MetricSeries, MetricSummary } from "../../lib/api";
import {
  agoLabel,
  safeAnalyticalTime,
  safeCorrelations,
  safeMetrics,
  safeSeries,
  viewingParticipant,
} from "../../lib/load";

export const REL_RANGES = ["30d", "90d", "1y", "all"];

// Display name from the catalog, else a prettified metric-id tail (the
// /compare fallback idiom) - never a raw dotted id in running copy.
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

// Normalize one side of the pair to its own 0-1 range for the overlay chart.
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
        {r === null ? "-" : r.toFixed(2)}
      </td>
      <td className="mono">{row.method ?? "-"}</td>
      <td className="mono">
        {row.p_value === null ? "-" : `p=${row.p_value.toFixed(3)}`}
        {row.p_value !== null && !significant && <span className="rel-weak"> · weak</span>}
      </td>
      <td className="mono">{row.period_days ? `${row.period_days}d` : "-"}</td>
      <td className="mono">{agoLabel(row.created_at)}</td>
    </tr>
  );
}

// Both reads failed ⇒ backend unreachable, and the page says so: demo
// correlations never stand in for the person's own outside /demo. `rows` is
// null when the correlation read failed - a DIFFERENT state from a reachable
// backend with zero correlations (honest empty + the compute button).
async function loadCatalog() {
  const [metrics, correlations, participant] = await Promise.all([
    safeMetrics(),
    safeCorrelations(),
    viewingParticipant(),
  ]);
  return {
    unreachable: metrics === null && correlations === null,
    rows: correlations,
    rowsState: correlationsState(correlations, participant),
    catalog: metrics ?? [],
  };
}

// Correlations are the primary person's analysis: with a participant selected
// the read is withheld, which is not an outage.
export function correlationsState(
  correlations: Correlation[] | null,
  viewingParticipant: boolean,
): "data" | "not-for-person" | "unreachable" {
  if (correlations !== null) return "data";
  return viewingParticipant ? "not-for-person" : "unreachable";
}

export async function ComputedRelationshipsSection({ range }: { range: string }) {
  const { rows, rowsState, catalog } = await loadCatalog();
  return (
    <section className="lead">
      <article className="card">
        <div className="rel-head">
          <h2>Computed relationships</h2>
          <RunCorrelationButton />
        </div>
        <p className="rel-sub">
          Cross-metric correlations the statistical engine computed and persisted - with method,
          p-value, and window. Click a pair to explore it below.
        </p>
        {rows === null ? (
          <p className="empty">
            {rowsState === "not-for-person"
              ? "Computed relationships cover the primary person only."
              : "The Observatory API did not answer, so computed relationships cannot be shown right now."}
          </p>
        ) : rows.length === 0 ? (
          <p className="empty">
            No correlations computed yet - they appear once the engine runs over enough paired
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
  );
}

export async function ExplorePairSection({
  aId,
  bId,
  range,
}: {
  aId: string;
  bId: string;
  range: string;
}) {
  const [{ unreachable, catalog }, analyticalTime] = await Promise.all([loadCatalog(), safeAnalyticalTime()]);
  const timeBasis = analyticalTime ?? UTC_TIME_BASIS;

  // Pair series are read live. With the backend unreachable there is nothing
  // to read, and the section says so instead of drawing a demo pair.
  let seriesA: MetricSeries | null = null;
  let seriesB: MetricSeries | null = null;
  const pairChosen = Boolean(aId && bId && aId !== bId);
  if (pairChosen && !unreachable) {
    [seriesA, seriesB] = await Promise.all([safeSeries(aId, range), safeSeries(bId, range)]);
  }

  const pairs: AlignedPair[] = seriesA && seriesB ? alignDaily(seriesA.points, seriesB.points, timeBasis) : [];
  const stat = pearson(pairs);
  const nameA = aId ? prettyName(catalog, aId) : "";
  const nameB = bId ? prettyName(catalog, bId) : "";
  const overlay: ChartSeries[] =
    pairs.length >= 2
      ? [
          {
            label: nameA,
            points: pairs.map((pair, index) => ({ t: pair.day, value: ownScale(pairs.map((p) => p.a))[index] })),
          },
          {
            label: nameB,
            points: pairs.map((pair, index) => ({ t: pair.day, value: ownScale(pairs.map((p) => p.b))[index] })),
          },
        ]
      : [];
  const days = pairs.map((p) => p.day).sort();
  const overlayDomain: [string, string] | undefined =
    days.length >= 2 ? [days[0], days[days.length - 1]] : undefined;

  const options = catalog
    .map((m) => ({ id: m.id, display_name: m.display_name, category: m.category }))
    .sort((x, y) => x.display_name.localeCompare(y.display_name));

  return (
    <>
      <section className="lead">
        <article className="card">
          <h2>Explore a pair</h2>
          <p className="rel-sub">
            Day means over shared days - both signals kept verbatim, each on its own scale.
          </p>
          <p className="meta">{timeBasisLabel(timeBasis)}</p>
          <RelateControls metrics={options} ranges={REL_RANGES} />

          {!pairChosen && aId && aId === bId && (
            <p className="empty">Pick two different signals.</p>
          )}
          {!pairChosen && !(aId && aId === bId) && (
            <p className="empty">Pick two signals - or click a computed pair above.</p>
          )}
          {pairChosen && unreachable && (
            <p className="empty">The Observatory API did not answer, so this pair cannot be explored right now.</p>
          )}
          {pairChosen && !unreachable && (!seriesA || !seriesB) && (
            <p className="empty">Couldn’t load one of the series - try another pair or range.</p>
          )}
          {pairChosen && seriesA && seriesB && pairs.length < CORRELATION_MIN_DAYS && (
            <p className="empty">
              Only {pairs.length} shared day{pairs.length === 1 ? "" : "s"} in this range - at
              least {CORRELATION_MIN_DAYS} are needed before a coefficient means anything.
            </p>
          )}
          {pairChosen && seriesA && seriesB && pairs.length >= CORRELATION_MIN_DAYS && (
            <>
              <div className="rel-stat mono">
                r = {stat ? stat.r.toFixed(2) : "-"} · n = {pairs.length} shared days · exploratory
                (no p-value)
              </div>
              <MultiSeriesChart series={overlay} dateDomain={overlayDomain} />
              <p className="rel-note">
                Each curve is scaled to its own range - compare shape and timing, not magnitude.
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
          ? "relationships unavailable · nothing left this host"
          : "correlation ≠ causation · computed on this host · nothing left this host"}
      </footer>
    </>
  );
}
