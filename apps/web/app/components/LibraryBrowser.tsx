"use client";

import Link from "next/link";
import type { CSSProperties } from "react";
import { useMemo, useState } from "react";

import { PinButton } from "./PinButton";

const CATEGORY_COLORS: Record<string, string> = {
  vital: "var(--signal)",
  cardio: "var(--down)",
  activity: "var(--accent)",
  sleep: "var(--sleep-core)",
  body: "var(--warn)",
  nutrition: "var(--up)",
  mind: "var(--experiment)",
};

const FALLBACK_COLORS = ["var(--signal)", "var(--accent)", "var(--warn)", "var(--experiment)", "var(--up)"];

function categoryColor(category: string): string {
  if (CATEGORY_COLORS[category]) return CATEGORY_COLORS[category];
  let hash = 0;
  for (const ch of category) hash = (hash * 31 + ch.charCodeAt(0)) % 997;
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length];
}

function coverageStyle(row: LibraryRow): CSSProperties {
  const pct = row.count === 0 ? 0 : Math.min(100, Math.max(8, Math.round((row.days / 90) * 100)));
  return { "--lib-fill": `${pct}%` } as CSSProperties;
}

function statusLabel(row: LibraryRow): string {
  if (row.analyzable) return "Ready";
  if (row.count > 0) return "Collecting";
  return "No data";
}

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
      if (!q) return true;
      return (
        row.name.toLowerCase().includes(q) ||
        row.id.toLowerCase().includes(q) ||
        row.category.toLowerCase().includes(q)
      );
    });
  }, [rows, query, category, withDataOnly]);

  const grouped = useMemo(() => {
    const byCat = new Map<string, LibraryRow[]>();
    for (const row of filtered) {
      const list = byCat.get(row.category) ?? [];
      list.push(row);
      byCat.set(row.category, list);
    }
    return [...byCat.entries()].sort((a, b) => {
      const dataA = a[1].some((r) => r.count > 0) ? 0 : 1;
      const dataB = b[1].some((r) => r.count > 0) ? 0 : 1;
      return dataA - dataB || a[0].localeCompare(b[0]);
    });
  }, [filtered]);

  const withData = rows.filter((row) => row.count > 0);
  const analyzable = rows.filter((row) => row.analyzable);
  const pinned = rows.filter((row) => row.pinned);
  const freshest = withData
    .filter((row) => row.lastAt)
    .sort((a, b) => new Date(b.lastAt ?? 0).getTime() - new Date(a.lastAt ?? 0).getTime())[0];

  return (
    <>
      <div className="lib-overview-grid">
        <article className="card lib-overview-card">
          <span>With data</span>
          <strong>{withData.length}</strong>
          <em>of {rows.length} canonical signals</em>
        </article>
        <article className="card lib-overview-card">
          <span>Analysis ready</span>
          <strong>{analyzable.length}</strong>
          <em>enough history for trends</em>
        </article>
        <article className="card lib-overview-card">
          <span>Pinned today</span>
          <strong>{pinned.length}</strong>
          <em>{pinned.length ? "driving Today grid" : "use stars to focus"}</em>
        </article>
        <article className="card lib-overview-card">
          <span>Freshest signal</span>
          <strong>{freshest ? freshest.lastLabel : "none"}</strong>
          <em>{freshest?.name ?? "waiting for first sync"}</em>
        </article>
      </div>

      <div className="card lib-toolbar">
        <input
          type="search"
          className="lib-search"
          placeholder="Search signals..."
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
          <input type="checkbox" checked={withDataOnly} onChange={(e) => setWithDataOnly(e.target.checked)} />
          With data only
        </label>
        <span className="lib-count mono">
          {filtered.length} of {rows.length}
        </span>
      </div>

      {grouped.length === 0 && (
        <p className="empty" style={{ marginTop: 16 }}>
          Nothing matches. Clear search or include signals without data yet.
        </p>
      )}

      {grouped.map(([cat, list]) => (
        <section key={cat} className="lib-group">
          <div className="section-label lib-group-label">
            <span className="cat-dot" style={{ background: categoryColor(cat) }} aria-hidden />
            <span>{cat}</span>
            <span className="lib-group-count">{list.length}</span>
          </div>
          <div className="card lib-card">
            {list.map((row) => (
              <div key={row.id} className={`lib-row ${row.count === 0 ? "lib-row-empty" : ""}`}>
                <PinButton metricId={row.id} pinned={row.pinned} />
                <div className="lib-row-body">
                  <div className="lib-row-titleline">
                    <Link href={`/library/${encodeURIComponent(row.id)}`} className="lib-name">
                      {row.name}
                      {row.unit && <span className="lib-unit mono">{row.unit}</span>}
                    </Link>
                    <span className={`lib-status ${row.analyzable ? "ready" : ""}`}>{statusLabel(row)}</span>
                  </div>
                  <div className="lib-row-meta">
                    <span>{row.valueType}</span>
                    <span>{row.count > 0 ? `last ${row.lastLabel}` : "not observed yet"}</span>
                    <span>{row.days} days covered</span>
                  </div>
                  <div className="lib-row-track" style={coverageStyle(row)} aria-hidden>
                    <span />
                  </div>
                </div>
                <div className="lib-row-stats">
                  <strong>{row.count.toLocaleString()}</strong>
                  <span>observations</span>
                </div>
                <Link href={`/library/${encodeURIComponent(row.id)}`} className="lib-open">
                  Open
                </Link>
              </div>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
