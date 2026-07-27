import type { DowCell } from "../lib/analytics";

// Weekday pivot bars (Grafana avg-by-weekday). Pure presentational; the page
// reduces points via analytics.dayOfWeekPivot. Today's bar gets an accent tint
// so the user can spot their current-day pattern at a glance.
export function DayOfWeekChart({
  cells,
  unit,
  todayDow,
}: {
  cells: DowCell[];
  unit?: string;
  todayDow?: number | null;
}) {
  const max = Math.max(...cells.map((c) => c.value), 1);
  return (
    <ul className="dow-list">
      {cells.map((c) => (
        <li className={`dow-row${todayDow != null && c.dow === todayDow ? " today" : ""}`} key={c.dow}>
          <span className="dow-label">{c.label}</span>
          <span className="dow-track">
            <span className="dow-fill" style={{ width: `${c.n ? Math.round((c.value / max) * 100) : 0}%` }} />
          </span>
          <span className="dow-val">
            {c.n ? c.value : "-"}
            {c.n && unit ? ` ${unit}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
