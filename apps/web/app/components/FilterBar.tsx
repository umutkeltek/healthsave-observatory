"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

// A thin client island: it holds NO data. It reads the current selection from
// the URL and writes the next selection back to the URL via router.replace
// (scroll-preserving) — the server component re-fetches and re-renders. This is
// the URL-as-state pattern (mirrors ExperimentActions); every view stays
// deep-linkable and the X-API-Key never leaves the server.

export type MetricOption = { id: string; display_name: string; category: string };

const SORTS = [
  { value: "", label: "Default order" },
  { value: "name", label: "Name (A–Z)" },
  { value: "recent", label: "Latest value" },
  { value: "coverage", label: "Most readings" },
];

export type DeviceOption = { id: string; label: string };

export function FilterBar({
  metrics,
  categories,
  sources,
  devices,
  ranges,
}: {
  metrics: MetricOption[];
  categories: string[];
  sources: string[];
  devices: DeviceOption[];
  ranges: string[];
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const range = params.get("range") ?? "7d";
  const category = params.get("category") ?? "";
  const metric = params.get("metric") ?? "";
  const source = params.get("source") ?? "";
  const device = params.get("device") ?? "";
  const sort = params.get("sort") ?? "";

  function update(mutate: (next: URLSearchParams) => void) {
    const next = new URLSearchParams(params.toString());
    mutate(next);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  function set(key: string, value: string) {
    update((next) => {
      if (value) next.set(key, value);
      else next.delete(key);
      // Changing the category clears a now-inconsistent specific metric.
      if (key === "category") next.delete("metric");
    });
  }

  // Only offer metrics within the chosen category (if any), so the two facets stay coherent.
  const metricOptions = category ? metrics.filter((m) => m.category === category) : metrics;
  const active = Boolean(metric || category || source || device || sort || range !== "7d");

  return (
    <div className="filter-bar" role="search" aria-label="Filter metrics">
      <label className="filter-field">
        <span className="filter-label">Category</span>
        <select className="filter-select" value={category} onChange={(e) => set("category", e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>

      <label className="filter-field">
        <span className="filter-label">Metric</span>
        <select className="filter-select" value={metric} onChange={(e) => set("metric", e.target.value)}>
          <option value="">All metrics</option>
          {metricOptions.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
            </option>
          ))}
        </select>
      </label>

      <label className="filter-field">
        <span className="filter-label">Source</span>
        <select className="filter-select" value={source} onChange={(e) => set("source", e.target.value)}>
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>

      {devices.length > 0 && (
        <label className="filter-field">
          <span className="filter-label">Device</span>
          <select className="filter-select" value={device} onChange={(e) => set("device", e.target.value)}>
            <option value="">All devices</option>
            {devices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      )}

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

      <label className="filter-field">
        <span className="filter-label">Sort</span>
        <select className="filter-select" value={sort} onChange={(e) => set("sort", e.target.value)}>
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </label>

      {active && (
        <button
          type="button"
          className="btn-ghost filter-clear"
          onClick={() => router.replace(pathname, { scroll: false })}
        >
          Clear
        </button>
      )}
    </div>
  );
}
