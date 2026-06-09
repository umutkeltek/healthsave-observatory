import type { ZoneCount } from "../lib/analytics";

// HR-zone distribution (Grafana zones pie) as a stacked bar + legend. Pure
// presentational; the page reduces points via analytics.hrZoneHistogram.
const ZONE_COLORS = ["var(--up)", "var(--signal)", "var(--accent)", "var(--warn)", "var(--down)"];

export function ZoneBar({ zones }: { zones: ZoneCount[] }) {
  const total = zones.reduce((sum, z) => sum + z.count, 0);
  if (total === 0) {
    return <p className="empty">No heart-rate samples in range.</p>;
  }
  return (
    <div className="zonebar">
      <div className="zone-track">
        {zones.map((z, i) =>
          z.count > 0 ? (
            <span
              key={z.zone}
              className="zone-seg"
              style={{ width: `${(z.count / total) * 100}%`, background: ZONE_COLORS[i % ZONE_COLORS.length] }}
              title={`${z.zone} ${z.label}: ${z.count}`}
            />
          ) : null,
        )}
      </div>
      <ul className="zone-legend">
        {zones.map((z, i) => (
          <li className="zone-legend-item" key={z.zone}>
            <span className="zone-dot" style={{ background: ZONE_COLORS[i % ZONE_COLORS.length] }} />
            {z.zone} {z.label}
            <span className="zone-pct">{Math.round((z.count / total) * 100)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
