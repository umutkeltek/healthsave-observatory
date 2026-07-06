import type { TodayHighlight } from "./RecoveryHero";

// The sync-plumbing strip, relocated OUT of the emotional hero (per the
// instrument-grammar restructure): Last sync / Signals / Ready / Changes, plus
// the freshness affordance. All four facts stay reachable; nothing is deleted —
// they simply no longer compete with the lead finding.
export function TodayPlumbing({ highlights, live }: { highlights: TodayHighlight[]; live: boolean }) {
  if (highlights.length === 0) return null;
  return (
    <section className="today-plumbing" aria-label="Sync status">
      <div className="today-plumbing-head">
        <span>Sync</span>
        <strong className={live ? "" : "watch"}>{live ? "Fresh" : "Check sync"}</strong>
      </div>
      <div className="today-plumbing-grid">
        {highlights.map((item) => (
          <div key={item.label} className={`today-glance-item ${item.tone === "watch" ? "watch" : ""}`}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
            <em>{item.hint}</em>
          </div>
        ))}
      </div>
    </section>
  );
}
