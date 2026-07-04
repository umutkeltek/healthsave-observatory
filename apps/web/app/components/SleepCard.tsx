import type { MetricSeries } from "../lib/api";

// Sleep-stage colours come from the design tokens (theme-aware) rather than
// hardcoded hex, so they stay coherent with the palette in light and dark.
const STAGE_COLOR: Record<string, string> = {
  awake: "var(--sleep-awake)",
  rem: "var(--sleep-rem)",
  core: "var(--sleep-core)",
  deep: "var(--sleep-deep)",
};

const STAGE_LABEL: Record<string, string> = {
  awake: "Awake",
  rem: "REM",
  core: "Core",
  deep: "Deep",
};

export function SleepCard({ series }: { series: MetricSeries | null }) {
  if (!series) {
    return (
      <article className="card">
        <h2>Sleep</h2>
        <p className="empty">Backend unreachable - start HealthSave Observatory and sync from the app.</p>
      </article>
    );
  }

  const stages = series.points.filter((p) => p.code !== null);
  if (stages.length === 0) {
    return (
      <article className="card">
        <h2>Sleep Stages</h2>
        <p className="empty">No sleep data yet - sync from HealthSave to see your night.</p>
      </article>
    );
  }

  const present = Array.from(new Set(stages.map((s) => s.code))).filter(
    (c): c is string => c !== null,
  );

  return (
    <article className="card">
      <h2>Sleep Stages</h2>
      <div className="hypnogram" role="img" aria-label="Sleep stage timeline">
        {stages.map((s, i) => (
          <span
            key={i}
            className="seg"
            style={{ background: STAGE_COLOR[s.code ?? ""] ?? "var(--neutral)" }}
            title={`${STAGE_LABEL[s.code ?? ""] ?? s.code} · ${new Date(s.t).toLocaleString()}`}
          />
        ))}
      </div>
      <div className="legend">
        {present.map((code) => (
          <span key={code} className="legend-item">
            <span className="dot" style={{ background: STAGE_COLOR[code] ?? "var(--neutral)" }} />
            {STAGE_LABEL[code] ?? code}
          </span>
        ))}
      </div>
      <div className="meta">
        {stages.length} stage segments · last {series.range}
      </div>
    </article>
  );
}
