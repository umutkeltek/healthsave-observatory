// The focus ribbon - the user's stated goal, framing Today. Presentation-only
// (v0): it names the goal, shows its target signals as 7-day sparkline chips,
// and links the picker. It never scores progress - that's a later, deterministic
// statistical module, not a UI feature.

import type { MetricSeries } from "../lib/api";
import type { FocusGoal } from "../lib/prefs";

const DIRECTION_LABEL: Record<FocusGoal["direction"], string> = {
  increase: "raising",
  decrease: "lowering",
  maintain: "holding",
};

function Spark({ series }: { series: MetricSeries | null }) {
  const values = (series?.points ?? []).map((p) => p.value).filter((v): v is number => v !== null);
  if (values.length < 2) return <span className="goal-spark empty-spark" aria-hidden />;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const w = 72;
  const h = 20;
  const step = w / (values.length - 1);
  const d = values
    .map((v, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${(h - ((v - min) / span) * (h - 4) - 2).toFixed(1)}`)
    .join(" ");
  return (
    <svg className="goal-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden>
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function GoalRibbon({
  goal,
  seriesById,
}: {
  goal: FocusGoal;
  seriesById: Map<string, MetricSeries>;
}) {
  return (
    <section className="goal-ribbon" aria-label={`Focus: ${goal.title}`}>
      <div className="goal-ribbon-head">
        <span className="goal-eyebrow">Focus</span>
        <span className="goal-title">{goal.title}</span>
        <span className="goal-dir mono">{DIRECTION_LABEL[goal.direction]}</span>
      </div>
      <div className="goal-metrics">
        {goal.metricIds.map((id) => {
          const series = seriesById.get(id) ?? null;
          const name = series?.metric.display_name ?? id.split(".").pop()?.replace(/_/g, " ") ?? id;
          return (
            <a key={id} className="goal-metric" href={`/library/${encodeURIComponent(id)}`}>
              <span className="goal-metric-name">{name}</span>
              <Spark series={series} />
            </a>
          );
        })}
      </div>
    </section>
  );
}
