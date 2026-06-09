import type { DowCell } from "../lib/analytics";

// Weekday pivot bars (Grafana avg-by-weekday). Pure presentational; the page
// reduces points via analytics.dayOfWeekPivot.
export function DayOfWeekChart({ cells, unit }: { cells: DowCell[]; unit?: string }) {
  const max = Math.max(...cells.map((c) => c.value), 1);
  return (
    <ul className="dow-list">
      {cells.map((c) => (
        <li className="dow-row" key={c.dow}>
          <span className="dow-label">{c.label}</span>
          <span className="dow-track">
            <span className="dow-fill" style={{ width: `${c.n ? Math.round((c.value / max) * 100) : 0}%` }} />
          </span>
          <span className="dow-val">
            {c.n ? c.value : "—"}
            {c.n && unit ? ` ${unit}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
