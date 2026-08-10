import type { HeatCell } from "../lib/analytics";
import { DOW_LABELS } from "../lib/analytics";
import { formatValue } from "../lib/format";

// "When in the week" heatmap — a 7×24 grid coloured by value intensity. Empty
// cells render blank. Weekday labels come from the shared analytics module so
// they never drift from dayOfWeekPivot / DayOfWeekChart definitions. The grid
// scrolls horizontally on narrow screens instead of crushing 24 cells into a
// phone-width row (the body's overflow-x:hidden would otherwise clip them).
export function HeatmapChart({ cells, unit }: { cells: HeatCell[]; unit?: string }) {
  const values = cells.map((c) => c.value).filter((v): v is number => v !== null);
  if (values.length === 0) {
    return <p className="empty">No data in range to chart.</p>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const byKey = new Map(cells.map((c) => [`${c.dow}-${c.hour}`, c]));

  return (
    <div className="heatmap">
      <div className="heatmap-scroll">
        {Array.from({ length: 7 }, (_, dow) => (
          <div className="heat-row" key={dow}>
            <span className="heat-rowlabel">{DOW_LABELS[dow]}</span>
            {Array.from({ length: 24 }, (_, hour) => {
              const cell = byKey.get(`${dow}-${hour}`);
              const v = cell?.value ?? null;
              // Relative intensity across the visible range. When every value
              // is equal we render a single honest mid tone instead of the
              // barely-tinted floor (a flat grid shouldn't look like a gradient).
              const intensity =
                v === null ? 0 : span === 0 ? 45 : Math.round((0.14 + ((v - min) / span) * 0.86) * 100);
              return (
                <span
                  key={hour}
                  className="heat-cell"
                  title={
                    v === null
                      ? `${DOW_LABELS[dow]} ${hour}:00 - no data`
                      : `${DOW_LABELS[dow]} ${hour}:00 - ${formatValue(v, unit)} (n=${cell?.n})`
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
    </div>
  );
}
