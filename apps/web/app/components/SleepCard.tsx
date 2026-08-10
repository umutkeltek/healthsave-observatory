import type { MetricSeries } from "../lib/api";
import { STAGE_COLOR, STAGE_LABEL } from "../lib/sleep";

// Sleep-stage colours come from the design tokens (theme-aware) rather than
// hardcoded hex, so they stay coherent with the palette in light and dark.
const STAGE_NEUTRAL = "var(--neutral)";

// Unknown stage codes (e.g. a new "outOfBed" code the backend starts sending)
// collapse to a neutral chip + "Other" label instead of leaking the raw code.
function stageLabel(code: string | null): string {
  return (code && STAGE_LABEL[code]) || "Other";
}
function stageColor(code: string | null): string {
  return (code && STAGE_COLOR[code]) || STAGE_NEUTRAL;
}

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
            style={{ background: stageColor(s.code) }}
            title={`${stageLabel(s.code)} · ${new Date(s.t).toLocaleString()}`}
          />
        ))}
      </div>
      <div className="legend">
        {present.map((code) => (
          <span key={code} className="legend-item">
            <span className="dot" style={{ background: stageColor(code) }} />
            {stageLabel(code)}
          </span>
        ))}
      </div>
      <div className="meta">
        {stages.length} stage segments · last {series.range}
      </div>
    </article>
  );
}
