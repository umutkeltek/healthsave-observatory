"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import type { MetricOption } from "./FilterBar";

// URL-state controls for /relationships: signal A, signal B, range. Holds no
// data - writes the query string and lets the server component re-fetch
// (the CompareControls idiom).
// `selected` is the page's own parse of the URL (app/relationships/page.tsx):
// a malformed signal id it dropped is not shown as chosen here.
export function RelateControls({
  metrics,
  ranges,
  selected,
}: {
  metrics: MetricOption[];
  ranges: string[];
  selected: { a: string; b: string; range: string };
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { a, b, range } = selected;

  function set(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const picker = (label: string, key: "a" | "b", value: string) => (
    <label className="filter-field">
      <span className="filter-label">{label}</span>
      <select className="filter-select" value={value} onChange={(e) => set(key, e.target.value)}>
        <option value="">Choose a signal</option>
        {metrics.map((m) => (
          <option key={m.id} value={m.id}>
            {m.display_name}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="filter-bar" role="search" aria-label="Relationship controls">
      {picker("Signal A", "a", a)}
      {picker("Signal B", "b", b)}
      <label className="filter-field">
        <span className="filter-label">Range</span>
        <select className="filter-select" value={range} onChange={(e) => set("range", e.target.value)}>
          {ranges.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
