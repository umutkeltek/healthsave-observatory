"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import type { MetricOption } from "./FilterBar";

// URL-state controls for /compare: metric, comparison mode, range. Holds no
// data — writes the query string and lets the server component re-fetch.
export function CompareControls({ metrics, ranges }: { metrics: MetricOption[]; ranges: string[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const metric = params.get("metric") ?? "";
  const mode = params.get("mode") === "source" ? "source" : "period";
  const range = params.get("range") ?? "30d";

  function set(key: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  return (
    <div className="filter-bar" role="search" aria-label="Comparison controls">
      <label className="filter-field">
        <span className="filter-label">Metric</span>
        <select className="filter-select" value={metric} onChange={(e) => set("metric", e.target.value)}>
          {metric === "" && <option value="">Default metric</option>}
          {metrics.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
            </option>
          ))}
        </select>
      </label>

      <label className="filter-field">
        <span className="filter-label">Compare</span>
        <select className="filter-select" value={mode} onChange={(e) => set("mode", e.target.value)}>
          <option value="period">Period vs previous</option>
          <option value="source">Source vs source</option>
        </select>
      </label>

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
