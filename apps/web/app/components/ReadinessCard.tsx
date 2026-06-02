import type { MetricReadiness, Readiness } from "../lib/api";

// Human-meaningful labels for the per-metric gates the backend grades.
const GATE_LABELS: Record<string, string> = {
  anomaly_detection: "Anomalies",
  trend_analysis: "Trends",
};

// Data older than this is likely behind because HealthKit can't sync while the
// iPhone is locked — we say so rather than pretending freshness.
const STALE_AFTER_MS = 24 * 60 * 60 * 1000;

function formatAgo(iso: string | null): string {
  if (!iso) return "never";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function isStale(iso: string | null): boolean {
  if (!iso) return true;
  return Date.now() - new Date(iso).getTime() > STALE_AFTER_MS;
}

function GateBadge({ label, verdict }: { label: string; verdict: MetricReadiness["analyzable"][string] }) {
  if (verdict.is_sufficient) {
    return <span className="badge ready">{label} ✓</span>;
  }
  const more =
    verdict.days_until_sufficient != null ? `${verdict.days_until_sufficient}d` : "more data";
  return <span className="badge waiting">{`${label} · ${more}`}</span>;
}

// Compact trend line for a readiness row — drawn from the metric's recent
// series when available, so the table shows shape, not just counts.
function MiniSparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const w = 88;
  const h = 26;
  const step = w / (values.length - 1);
  const d = values
    .map(
      (v, i) =>
        `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${(h - ((v - min) / span) * h).toFixed(1)}`,
    )
    .join(" ");
  return (
    <svg
      className="metric-spark"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      aria-hidden
    >
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function MetricRow({ metric, values }: { metric: MetricReadiness; values?: number[] }) {
  return (
    <li className="metric-row">
      <div className="metric-id">
        <span className="metric-name">{metric.display_name}</span>
        <span className="metric-cov">
          {metric.observation_count.toLocaleString()} readings · {metric.days_with_data} days
        </span>
      </div>
      {values && values.length >= 2 && <MiniSparkline values={values} />}
      <div className="badges">
        {Object.entries(GATE_LABELS).map(([key, label]) => {
          const verdict = metric.analyzable[key];
          return verdict ? <GateBadge key={key} label={label} verdict={verdict} /> : null;
        })}
      </div>
    </li>
  );
}

export function ReadinessCard({
  readiness,
  sparklines,
}: {
  readiness: Readiness | null;
  sparklines?: Record<string, number[]>;
}) {
  if (!readiness) {
    return (
      <article className="card readiness">
        <h2>Data Readiness</h2>
        <p className="empty">Backend unreachable — start datahub and sync from HealthSave.</p>
      </article>
    );
  }

  if (readiness.metrics.length === 0) {
    return (
      <article className="card readiness">
        <h2>Data Readiness</h2>
        <p className="empty">No data yet — sync from HealthSave to populate your hub.</p>
      </article>
    );
  }

  const stale = isStale(readiness.last_observation_at);

  return (
    <article className="card readiness">
      <h2>Data Readiness</h2>

      <div className="readiness-head">
        <div className="big">
          {readiness.summary.metrics_with_data}
          <span className="unit">metrics with data</span>
        </div>
        <div className={`freshness ${stale ? "down" : "up"}`}>
          {stale ? "▼" : "▲"} last reading {formatAgo(readiness.last_observation_at)}
        </div>
      </div>

      {stale && (
        <p className="note">
          Data may be behind — HealthKit only syncs while your iPhone is unlocked. Open HealthSave
          to catch up.
        </p>
      )}

      {readiness.sources.length > 0 && (
        <div className="chips">
          {readiness.sources.map((source) => (
            <span className="chip" key={source.source_plugin_id ?? "unknown"}>
              {source.source_plugin_id ?? "unknown"} · {source.observation_count.toLocaleString()}
            </span>
          ))}
        </div>
      )}

      <ul className="metric-rows">
        {readiness.metrics.map((metric) => (
          <MetricRow
            key={metric.metric_id}
            metric={metric}
            values={sparklines?.[metric.metric_id]}
          />
        ))}
      </ul>

      <div className="meta">{readiness.metrics.length} metrics · ✓ = ready to analyze now</div>
    </article>
  );
}
