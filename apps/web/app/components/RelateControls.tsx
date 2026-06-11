"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import type { MetricOption } from "./FilterBar";

// URL-state controls for /relationships: signal A, signal B, range. Holds no
// data — writes the query string and lets the server component re-fetch
// (the CompareControls idiom).
export function RelateControls({ metrics, ranges }: { metrics: MetricOption[]; ranges: string[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const range = params.get("range") ?? "90d";

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
