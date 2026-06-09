import type { HeatCell } from "../lib/analytics";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// "When in the week" heatmap — a 7×24 grid coloured by value intensity. Empty
// cells render blank. Pure presentational; the page reduces points via
// analytics.weekHourPivot.
export function HeatmapChart({ cells, unit }: { cells: HeatCell[]; unit?: string }) {
  const values = cells.map((c) => c.value).filter((v): v is number => v !== null);
  if (values.length === 0) {
    return <p className="empty">No data in range to chart.</p>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const byKey = new Map(cells.map((c) => [`${c.dow}-${c.hour}`, c]));

  return (
    <div className="heatmap">
      {Array.from({ length: 7 }, (_, dow) => (
        <div className="heat-row" key={dow}>
          <span className="heat-rowlabel">{DOW[dow]}</span>
          {Array.from({ length: 24 }, (_, hour) => {
            const cell = byKey.get(`${dow}-${hour}`);
            const v = cell?.value ?? null;
            const intensity = v === null ? 0 : Math.round((0.14 + ((v - min) / span) * 0.86) * 100);
            return (
              <span
                key={hour}
                className="heat-cell"
                title={
                  v === null
                    ? `${DOW[dow]} ${hour}:00 — no data`
                    : `${DOW[dow]} ${hour}:00 — ${v}${unit ? ` ${unit}` : ""} (n=${cell?.n})`
                }
                style={{
                  background: v === null ? "var(--raise)" : `color-mix(in srgb, var(--accent) ${intensity}%, transparent)`,
                }}
              />
            );
          })}
        </div>
      ))}
      <div className="heat-axis">
        <span>0h</span>
        <span>6h</span>
        <span>12h</span>
        <span>18h</span>
        <span>23h</span>
      </div>
    </div>
  );
}
