import type { Metadata } from "next";
import Link from "next/link";

import { detectDivergence, groupBySource } from "../../lib/analytics";
import { anomalyPinIndices } from "../../lib/annotations";
import { quantile } from "../../components/chart/scale";
import { comparability } from "../../lib/healthOpinion";
import { agoLabel, safeFindings, safeMetrics, safeReadiness, safeSeries } from "../../lib/load";
import { METRIC_NOTES } from "../../lib/metricNotes";
import { getPinnedMetrics } from "../../lib/prefs";
import { friendlyName } from "../../lib/provenance";
import { BaselineRibbon } from "../../components/BaselineRibbon";
import { MultiSeriesChart } from "../../components/MultiSeriesChart";
import { PinButton } from "../../components/PinButton";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Signal · HealthSave Observatory" };

const RANGES = ["7d", "30d", "90d", "1y"] as const;
type Range = (typeof RANGES)[number];

function numberLabel(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "-";
  const abs = Math.abs(value);
  if (abs >= 1000) return Math.round(value).toLocaleString();
  if (abs < 10 && !Number.isInteger(value)) return value.toFixed(1);
  return Math.round(value).toLocaleString();
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

  const [series, metrics, readiness, pinned, findings] = await Promise.all([
    metricId ? safeSeries(metricId, range) : Promise.resolve(null),
    safeMetrics(),
    safeReadiness(),
    getPinnedMetrics(),
    safeFindings(),
  ]);

  const metric = metrics?.find((m) => m.id === metricId) ?? series?.metric;
  const stat = readiness?.metrics.find((m) => m.metric_id === metricId);

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

  const points = series?.points ?? [];
  const numericPoints = points.filter((p): p is typeof p & { value: number } => p.value !== null);
  const values = numericPoints.map((p) => p.value);
  const sorted = [...values].sort((a, b) => a - b);
  const bySource = groupBySource(points);
  const sourceIds = [...bySource.keys()];
  const comp = comparability(metricId, sourceIds);
  const divergence = detectDivergence(points);
  const notes = METRIC_NOTES[metricId] ?? [];
  const multiSource = sourceIds.length > 1;
  const last = values.at(-1);

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
          label: friendlyName(sourceId),
          values: pts.map((p) => p.value).filter((v): v is number => v !== null),
        }))
        .filter((s) => s.values.length >= 2)
    : [];

  const sourceSummaries = [...bySource.entries()]
    .map(([sourceId, pts]) => ({
      id: sourceId,
      label: friendlyName(sourceId),
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
                    {r}
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
              <small>{range} range selected</small>
            </div>
          </div>

          <div className="lib-chart-panel">
            <div className="lib-chart-head">
              <h2>{multiSource ? "Source traces" : "Baseline trace"}</h2>
              <p>{multiSource ? "Each source remains independent." : "The band shows your own P25-P75 range."}</p>
            </div>
            {values.length >= 2 && !multiSource && (
              <BaselineRibbon
                values={values}
                anomalies={anomalies}
                height={132}
                axis={[`${range} ago`, "today"]}
                hoverLabels={numericPoints.map((p) =>
                  new Date(p.t).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
                )}
                unit={metric.canonical_unit}
              />
            )}
            {multiSource && perSourceSeries.length >= 1 && <MultiSeriesChart series={perSourceSeries} />}
            {values.length < 2 && (
              <p className="empty">
                {stat?.observation_count
                  ? `No numeric readings in the last ${range}. Try a longer range.`
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
