"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { PinButton } from "./PinButton";

// One row per canonical metric: registry metadata joined (server-side) with
// readiness stats. ~190 rows of metadata — trivially serializable, filtered
// entirely client-side.
export type LibraryRow = {
  id: string;
  name: string;
  category: string;
  unit: string | null;
  valueType: string;
  count: number;
  days: number;
  lastAt: string | null;
  lastLabel: string;
  analyzable: boolean;
  pinned: boolean;
};

export function LibraryBrowser({
  rows,
  categories,
  defaultWithData = true,
}: {
  rows: LibraryRow[];
  categories: string[];
  defaultWithData?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [withDataOnly, setWithDataOnly] = useState(defaultWithData);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (withDataOnly && row.count === 0) return false;
      if (category !== "all" && row.category !== category) return false;
      if (q && !row.name.toLowerCase().includes(q) && !row.id.includes(q)) return false;
      return true;
    });
  }, [rows, query, category, withDataOnly]);

  const grouped = useMemo(() => {
    const byCat = new Map<string, LibraryRow[]>();
    for (const row of filtered) {
      const list = byCat.get(row.category) ?? [];
      list.push(row);
      byCat.set(row.category, list);
    }
    // Categories with data first, then alphabetical.
    return [...byCat.entries()].sort((a, b) => {
      const dataA = a[1].some((r) => r.count > 0) ? 0 : 1;
      const dataB = b[1].some((r) => r.count > 0) ? 0 : 1;
      return dataA - dataB || a[0].localeCompare(b[0]);
    });
  }, [filtered]);

  return (
    <>
      <div className="lib-controls">
        <input
          type="search"
          className="lib-search"
          placeholder="Search signals…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search metrics"
        />
        <select
          className="lib-select"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label="Filter by category"
        >
          <option value="all">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <label className="lib-toggle">
          <input
            type="checkbox"
            checked={withDataOnly}
            onChange={(e) => setWithDataOnly(e.target.checked)}
          />
          With data only
        </label>
        <span className="lib-count mono">
          {filtered.length} of {rows.length}
        </span>
      </div>

      {grouped.length === 0 && (
        <p className="empty" style={{ marginTop: 16 }}>
          Nothing matches — clear the search or include signals without data yet.
        </p>
      )}

      {grouped.map(([cat, list]) => (
        <section key={cat} className="lib-group">
          <div className="section-label">{cat}</div>
          <div className="card lib-card">
            {list.map((row) => (
              <div key={row.id} className={`lib-row ${row.count === 0 ? "lib-row-empty" : ""}`}>
                <PinButton metricId={row.id} pinned={row.pinned} />
                <Link href={`/library/${encodeURIComponent(row.id)}`} className="lib-name">
                  {row.name}
                  {row.unit && <span className="lib-unit mono">{row.unit}</span>}
                </Link>
                <span className="lib-stats mono">
                  {row.count > 0 ? (
                    <>
                      {row.count.toLocaleString()} obs · {row.days}d · last {row.lastLabel}
                    </>
                  ) : (
                    "no data yet"
                  )}
                </span>
                {row.analyzable && <span className="lib-badge">analyzable</span>}
              </div>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
