"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useOptimistic, useTransition } from "react";

import type { MetricOption } from "./FilterBar";

// URL-state controls for /compare: metric, comparison mode, range. Holds no
// data - writes the query string and lets the server component re-fetch.
// `selected` is the page's own parse of the URL (app/compare/page.tsx), so the
// controls always show what the page shows; the raw query is only the base the
// next URL is built on.
export function CompareControls({
  metrics,
  ranges,
  selected,
}: {
  metrics: MetricOption[];
  ranges: string[];
  selected: { metric: string; mode: "period" | "source" | "device"; range: string };
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  // Show the pick at once and mark the bar busy while the page re-renders
  // (FilterBar idiom).
  const [pending, startTransition] = useTransition();
  const [shown, setShown] = useOptimistic(selected, (current, patch: Partial<typeof selected>) => ({
    ...current,
    ...patch,
  }));
  const { metric, mode, range } = shown;

  function set(key: keyof typeof selected, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const qs = next.toString();
    startTransition(() => {
      setShown({ [key]: value } as Partial<typeof selected>);
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    });
  }

  return (
    <div
      className="filter-bar"
      role="search"
      aria-label="Comparison controls"
      aria-busy={pending}
      data-pending={pending || undefined}
    >
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
          <option value="device">Device vs device</option>
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
