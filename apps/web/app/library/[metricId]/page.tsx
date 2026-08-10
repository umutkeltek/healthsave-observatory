import type { Metadata } from "next";
import Link from "next/link";

import { detectDivergence, groupBySource } from "../../lib/analytics";
import { anomalyPinIndices } from "../../lib/annotations";
import { quantile } from "../../components/chart/scale";
import { formatValue } from "../../lib/format";
import { comparability } from "../../lib/healthOpinion";
import { agoLabel, safeFindings, safeMetrics, safeReadiness, safeSeriesWithFallback, safeStreams } from "../../lib/load";
import { METRIC_NOTES } from "../../lib/metricNotes";
import { getPinnedMetrics } from "../../lib/prefs";
import { friendlyName, shortId } from "../../lib/provenance";
import { rangeLabel, seriesCoverage, shortDate } from "../../lib/ranges";
import { hasOwnerDailyTotalSemantics, summarizeNumericSeries } from "../../lib/series";
import { BaselineRibbon } from "../../components/BaselineRibbon";
import { MultiSeriesChart } from "../../components/MultiSeriesChart";
import { PinButton } from "../../components/PinButton";

export const revalidate = 30;
export const metadata: Metadata = { title: "Signal · HealthSave Observatory" };

const RANGES = ["7d", "30d", "90d", "1y", "all"] as const;
type Range = (typeof RANGES)[number];

const RANGE_CHIPS: Record<Range, string> = {
  "7d": "7 days",
  "30d": "30 days",
  "90d": "90 days",
  "1y": "1 year",
  all: "All time",
};

function numberLabel(value: number | null | undefined): string {
  return formatValue(value, undefined, { nullLabel: "-" });
}

function latestLabel(points: { t: string; value: number | null }[]): string {
  const latest = [...points].sort((a, b) => new Date(b.t).getTime() - new Date(a.t).getTime())[0];
  return latest ? agoLabel(latest.t) : "no recent reading";
}

export default async function MetricDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ metricId: string }>;
  searchParams: Promise<{ range?: string }>;
}) {
  const { metricId: rawId } = await params;
  const metricId = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/.test(rawId) ? rawId : "";
  const sp = await searchParams;
  const range: Range = RANGES.includes(sp.range as Range) ? (sp.range as Range) : "30d";

  const [{ requested: series, fallback: fallbackSeries }, metrics, readiness, pinned, findings, streams] = await Promise.all([
    metricId ? safeSeriesWithFallback(metricId, range) : Promise.resolve({ requested: null, fallback: null }),
    safeMetrics(),
    safeReadiness(),
    getPinnedMetrics(),
    safeFindings(),
    safeStreams(),
  ]);

  const metric = metrics?.find((m) => m.id === metricId) ?? series?.metric;
  const stat = readiness?.metrics.find((m) => m.metric_id === metricId);
  const effective = series ?? fallbackSeries;
  const usingFallback = series === null && fallbackSeries !== null;
  const coverage = effective ? seriesCoverage(effective.points) : null;

  if (!metric) {
    return (
      <section className="lead">
        <article className="card lib-unknown">
          <h2>Unknown signal</h2>
          <p className="empty">That signal is not in the metric registry.</p>
          <Link href="/library" className="btn">
            Back to Library
          </Link>
        </article>
      </section>
    );
  }

  const points = effective?.points ?? [];
  const numericPoints = points.filter((p): p is typeof p & { value: number } => p.value !== null);
  const values = numericPoints.map((p) => p.value);
  const isOwnerDailyTotal = hasOwnerDailyTotalSemantics(points);
  const sorted = [...values].sort((a, b) => a - b);
  const { latest: latestObs } = summarizeNumericSeries(points);
  const last = latestObs?.value ?? null;
  const bySource = groupBySource(points);
  const sourceIds = [...bySource.keys()];

  // Resolve a point's source_id to a human label: prefer the device from the
  // stream registry, then a known integration name, then a shortened id — never
  // surface a raw 36-char UUID as the source name.
  const streamLabel = new Map(
    (streams ?? []).map((s) => [s.id, s.device_label ?? friendlyName(s.source_plugin_id)] as const),
  );
  const sourceLabel = (id: string): string => {
    const mapped = streamLabel.get(id);
    if (mapped) return mapped;
    const friendly = friendlyName(id);
    if (friendly !== id) return friendly;
    return /^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(id) ? `Stream ${shortId(id)}` : id;
  };
  const comp = comparability(metricId, sourceIds);
  const divergence = detectDivergence(points);
  const notes = METRIC_NOTES[metricId] ?? [];
  const multiSource = sourceIds.length > 1;

  const stats =
    sorted.length >= 2
      ? [
          { label: "min", value: sorted[0] },
          { label: "P25", value: quantile(sorted, 0.25) },
          { label: "median", value: quantile(sorted, 0.5) },
          { label: "P75", value: quantile(sorted, 0.75) },
          { label: "max", value: sorted[sorted.length - 1] },
          { label: "last", value: last },
        ]
      : [];

  const perSourceSeries = multiSource
    ? [...bySource.entries()]
        .map(([sourceId, pts]) => ({
          label: sourceLabel(sourceId),
          points: pts.flatMap((point) =>
            point.value === null ? [] : [{ t: point.t, value: point.value }],
          ),
        }))
        .filter((s) => s.points.length >= 2)
    : [];

  const sourceSummaries = [...bySource.entries()]
    .map(([sourceId, pts]) => ({
      id: sourceId,
      label: sourceLabel(sourceId),
      count: pts.length,
      numericCount: pts.filter((p) => p.value !== null).length,
      last: latestLabel(pts),
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));

  const anomalies = anomalyPinIndices(
    numericPoints.map((p) => p.t),
    findings,
    metricId,
  );

  return (
    <>
      <section className="lead">
        <article className="card lib-detail-card">
          <div className="lib-detail-head">
            <div>
              <div className="hero-eyebrow">
                {metric.category} / {metric.value_type}
                {metric.canonical_unit ? ` / ${metric.canonical_unit}` : ""}
              </div>
              <h1 className="lib-detail-title">{metric.display_name}</h1>
            </div>
            <div className="lib-detail-actions">
              <PinButton metricId={metricId} pinned={pinned.includes(metricId)} />
              <nav className="lib-ranges" aria-label="Range">
                {RANGES.map((r) => (
                  <Link
                    key={r}
                    href={`/library/${encodeURIComponent(metricId)}?range=${r}`}
                    className={`chip ${r === range ? "chip-active" : ""}`}
                  >
                    {RANGE_CHIPS[r]}
                  </Link>
                ))}
              </nav>
            </div>
          </div>

          <div className="lib-detail-summary">
            <div className="lib-focus-number">
              <span>Latest</span>
              <strong>
                {numberLabel(last)}
                {metric.canonical_unit && <em>{metric.canonical_unit}</em>}
              </strong>
              <small>{stat ? `last ${agoLabel(stat.last_observation_at)}` : "no readiness stats"}</small>
            </div>
            <div className="lib-summary-tile">
              <span>Observations</span>
              <strong>{(stat?.observation_count ?? values.length).toLocaleString()}</strong>
              <small>{stat ? `${stat.days_with_data} days covered` : `${values.length} in range`}</small>
            </div>
            <div className="lib-summary-tile">
              <span>Sources</span>
              <strong>{sourceIds.length || "-"}</strong>
              <small>{multiSource ? "kept separate" : "single stream"}</small>
            </div>
            <div className="lib-summary-tile">
              <span>Trend status</span>
              <strong>{Object.values(stat?.analyzable ?? {}).some((g) => g.is_sufficient) ? "Ready" : "Building"}</strong>
              <small>{rangeLabel(range)} range selected</small>
            </div>
          </div>

          <div className="lib-chart-panel">
            <div className="lib-chart-head">
              <h2>{isOwnerDailyTotal ? "Daily total trace" : multiSource ? "Source traces" : "Baseline trace"}</h2>
              <p>
                {isOwnerDailyTotal
                  ? "One all-source total per local calendar day. Its API timestamp is that day's local midnight expressed in UTC."
                  : multiSource
                    ? "Each source remains independent."
                    : "The band shows your own P25-P75 range."}
              </p>
            </div>
            {values.length >= 2 && !multiSource && (
              <BaselineRibbon
                values={values}
                anomalies={anomalies}
                height={132}
                axis={[`${rangeLabel(range)}`, "today"]}
                hoverLabels={numericPoints.map((p) =>
                  new Date(p.t).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
                )}
                unit={metric.canonical_unit}
              />
            )}
            {multiSource && perSourceSeries.length >= 1 && (
              <MultiSeriesChart
                series={perSourceSeries}
                unit={metric.canonical_unit}
                dateDomain={
                  numericPoints.length >= 2
                    ? [numericPoints[0].t, numericPoints[numericPoints.length - 1].t]
                    : undefined
                }
              />
            )}
            {values.length < 2 && (
              <p className="empty lib-fallback-note">
                {stat?.observation_count
                  ? `No numeric readings in the ${rangeLabel(range)} range. Try a longer range.`
                  : usingFallback
                    ? coverage
                      ? `No data in the requested ${rangeLabel(range)} range — showing all available observations (${coverage.count} readings, ${shortDate(coverage.first)} → ${shortDate(coverage.last)}).`
                      : `No data in the requested ${rangeLabel(range)} range, and no data available overall.`
                    : "No data for this signal yet. It appears here when a source streams it."}
              </p>
            )}
          </div>

          {stats.length > 0 && (
            <div className="lib-stats-strip mono">
              {stats.map((s) => (
                <span key={s.label}>
                  <span className="lib-stat-label">{s.label}</span> {numberLabel(s.value)}
                </span>
              ))}
            </div>
          )}
        </article>
      </section>

      <section className="lead lib-detail-grid">
        <article className="card">
          <h2>Sources</h2>
          {sourceSummaries.length === 0 ? (
            <p className="empty">No sources contributed points in this range.</p>
          ) : (
            <div className="lib-source-list">
              {sourceSummaries.map((source) => (
                <div key={source.id} className="lib-source-row">
                  <div>
                    <strong>{source.label}</strong>
                    <span>{source.last}</span>
                  </div>
                  <p>
                    {source.numericCount.toLocaleString()} numeric / {source.count.toLocaleString()} total
                  </p>
                </div>
              ))}
            </div>
          )}
        </article>

        <article className="card">
          <h2>Interpretation</h2>
          {multiSource ? (
            <p className="lib-divergence">
              <strong>{sourceIds.length} sources stream this signal.</strong> Disagreeing sources stay separate.
              {divergence.diverged && divergence.gapPct !== null
                ? ` Current gap is about ${Math.round(divergence.gapPct)}%.`
                : ""}
              {comp.caveat ? ` ${comp.caveat}` : ""}
            </p>
          ) : (
            <p className="empty">Single-source signal. Compare source behavior when another stream contributes data.</p>
          )}
        </article>
      </section>

      {notes.length > 0 && (
        <section className="lead">
          <div className="card">
            <h2>How to read this</h2>
            <ul className="lib-notes">
              {notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        </section>
      )}

      <section className="lead">
        <p className="meta">
          <Link href="/library">Back to all signals</Link>
        </p>
      </section>
    </>
  );
}
