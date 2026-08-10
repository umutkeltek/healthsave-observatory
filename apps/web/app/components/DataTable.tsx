"use client";

import { useState } from "react";

import type { SeriesPoint } from "../lib/api";
import { formatValue } from "../lib/format";

// A sortable recent-readings table (the Grafana log-table capability). Local
// client sort by column - holds no data beyond the props. Capped to keep the
// DOM light. (A workout-specific log needs a v2 workouts endpoint that does not
// exist yet - this is the generic per-metric reading log.)
type Col = "t" | "value" | "source_id";
const CAP = 60;

// Render an ISO timestamp in the viewer's local timezone. `t` arrives as UTC
// ISO; slicing it raw (the old behaviour) printed UTC as if it were local and
// mislabelled every reading by the offset. This is a client component, so
// toLocaleString resolves in the browser tz.
function formatReadingTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function DataTable({ points, unit }: { points: SeriesPoint[]; unit?: string }) {
  const [col, setCol] = useState<Col>("t");
  const [dir, setDir] = useState<"asc" | "desc">("desc");

  function toggle(next: Col) {
    if (next === col) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setCol(next);
      setDir("desc");
    }
  }

  const rows = [...points]
    .sort((a, b) => {
      let cmp: number;
      if (col === "value") cmp = (a.value ?? Number.NEGATIVE_INFINITY) - (b.value ?? Number.NEGATIVE_INFINITY);
      else if (col === "source_id") cmp = a.source_id < b.source_id ? -1 : a.source_id > b.source_id ? 1 : 0;
      else cmp = a.t < b.t ? -1 : a.t > b.t ? 1 : 0;
      return dir === "asc" ? cmp : -cmp;
    })
    .slice(0, CAP);

  const arrow = (c: Col) => (c === col ? (dir === "asc" ? " ↑" : " ↓") : "");

  return (
    <div className="prov-scroll">
      <table className="prov datatable">
        <thead>
          <tr>
            <th scope="col">
              <button type="button" className="dt-sort" onClick={() => toggle("t")}>
                Time{arrow("t")}
              </button>
            </th>
            <th scope="col">
              <button type="button" className="dt-sort" onClick={() => toggle("value")}>
                Value{arrow("value")}
              </button>
            </th>
            <th scope="col">
              <button type="button" className="dt-sort" onClick={() => toggle("source_id")}>
                Source{arrow("source_id")}
              </button>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => (
            <tr key={`${p.t}-${p.source_id}-${i}`}>
              <td className="prov-sync">{formatReadingTime(p.t)}</td>
              <td className="dt-val">
                {formatValue(p.value, unit, { nullLabel: "-" })}
              </td>
              <td className="prov-hw">{p.source_id}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
