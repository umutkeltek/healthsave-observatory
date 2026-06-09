import type { SourceCount } from "../lib/analytics";

// Where the visible readings came from — count per source over the current
// filter/range, computed by analytics.distribution(). A provenance-at-a-glance
// strip; the /sources page carries the full chain of custody.
export function SourceDistribution({ dist }: { dist: SourceCount[] }) {
  if (dist.length === 0) return null;
  const total = dist.reduce((sum, d) => sum + d.count, 0);
  return (
    <div className="source-dist" aria-label="Readings by source">
      {dist.map((d) => {
        const pct = total ? Math.round((d.count / total) * 100) : 0;
        return (
          <span className="source-chip" key={d.source_id} title={`${d.count} readings`}>
            <span className="source-chip-name">{d.source_id}</span>
            <span className="source-chip-count">
              {d.count.toLocaleString()} · {pct}%
            </span>
          </span>
        );
      })}
    </div>
  );
}
