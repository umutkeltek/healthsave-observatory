import type { Metadata } from "next";
import Link from "next/link";

import { groupBySource } from "../../lib/analytics";
import { comparability } from "../../lib/healthOpinion";
import { agoLabel, safeMetrics, safeReadiness, safeSeries } from "../../lib/load";
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

function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  const next = sorted[base + 1];
  return next !== undefined ? sorted[base] + rest * (next - sorted[base]) : sorted[base];
}

export default async function MetricDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ metricId: string }>;
  searchParams: Promise<{ range?: string }>;
}) {
  const { metricId: rawId } = await params;
  const metricId = decodeURIComponent(rawId);
  const sp = await searchParams;
  const range: Range = RANGES.includes(sp.range as Range) ? (sp.range as Range) : "30d";

  const [series, metrics, readiness, pinned] = await Promise.all([
    safeSeries(metricId, range),
    safeMetrics(),
    safeReadiness(),
    getPinnedMetrics(),
  ]);

  const metric = metrics?.find((m) => m.id === metricId) ?? series?.metric ?? null;
  if (!metric) {
    return (
      <section className="lead">
        <div className="card">
          <h2>Unknown signal</h2>
          <p className="empty">
            “{metricId}” is not in the metric registry. <Link href="/library">Back to the Library</Link>.
          </p>
        </div>
      </section>
    );
  }

  const stat = readiness?.metrics.find((m) => m.metric_id === metricId);
  const points = series?.points ?? [];
  const values = points.map((p) => p.value).filter((v): v is number => v !== null);
  const sorted = [...values].sort((a, b) => a - b);
  const bySource = groupBySource(points);
  const sourceIds = [...bySource.keys()];
  const comp = comparability(metricId, sourceIds);
  const notes = METRIC_NOTES[metricId] ?? [];

  const stats =
    sorted.length >= 2
      ? [
          { label: "min", value: sorted[0] },
          { label: "P25", value: quantile(sorted, 0.25) },
          { label: "median", value: quantile(sorted, 0.5) },
          { label: "P75", value: quantile(sorted, 0.75) },
          { label: "max", value: sorted[sorted.length - 1] },
          { label: "last", value: values[values.length - 1] },
        ]
      : [];

  const multiSource = sourceIds.length > 1;
  const perSourceSeries = multiSource
    ? [...bySource.entries()]
        .map(([sourceId, pts]) => ({
          label: friendlyName(sourceId),
          values: pts.map((p) => p.value).filter((v): v is number => v !== null),
        }))
        .filter((s) => s.values.length >= 2)
    : [];

  return (
    <>
      <section className="lead">
        <div className="card">
          <div className="lib-detail-head">
            <div>
              <div className="hero-eyebrow">
                {metric.category} · {metric.value_type}
                {metric.canonical_unit ? ` · ${metric.canonical_unit}` : ""}
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

          {values.length >= 2 && !multiSource && (
            <BaselineRibbon values={values} height={120} axis={[`${range} ago`, "today"]} />
          )}

          {multiSource && perSourceSeries.length >= 1 && (
            <>
              <MultiSeriesChart series={perSourceSeries} />
              <p className="lib-divergence">
                <strong>{sourceIds.length} sources stream this signal.</strong> Each trace is kept
                separate — disagreeing sources are never averaged into an artificial consensus.
                {comp.caveat ? ` ${comp.caveat}` : ""}
              </p>
            </>
          )}

          {values.length < 2 && (
            <p className="empty">
              {stat?.observation_count
                ? `No numeric readings in the last ${range} — try a longer range.`
                : "No data for this signal yet. It appears here as soon as a source streams it."}
            </p>
          )}

          {stats.length > 0 && (
            <div className="lib-stats-strip mono">
              {stats.map((s) => (
                <span key={s.label}>
                  <span className="lib-stat-label">{s.label}</span> {Number(s.value.toFixed(1))}
                </span>
              ))}
            </div>
          )}

          <div className="meta" style={{ marginTop: 12 }}>
            {stat
              ? `${stat.observation_count.toLocaleString()} observations · ${stat.days_with_data} days with data · last ${agoLabel(stat.last_observation_at)}`
              : "No readiness stats yet."}
          </div>
        </div>
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
          <Link href="/library">← All signals</Link>
        </p>
      </section>
    </>
  );
}
