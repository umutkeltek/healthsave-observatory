"use client";

import { useState } from "react";

import type { ExportMetricInfo } from "../lib/api";

// Take-your-data-out card for /data: pick a metric, format, and window, then
// download through the server-side /api/export proxy (the key never reaches
// the browser). Driven by the backend's own exportable-metric list — names
// here are the legacy export names, not ontology ids.

const WINDOWS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last year" },
  { value: "all", label: "Everything" },
];

function dayLabel(iso: string | null): string {
  return iso ? iso.slice(0, 10) : "—";
}

export function ExportCard({ metrics }: { metrics: ExportMetricInfo[] | null }) {
  const available = (metrics ?? []).filter((m) => m.count > 0);
  const [metric, setMetric] = useState<string>(available[0]?.metric ?? "all");
  const [format, setFormat] = useState<"csv" | "json">("csv");
  const [window, setWindow] = useState("90");

  if (metrics === null) {
    return (
      <article className="card">
        <h2>Export</h2>
        <p className="empty">Backend unreachable — exports read straight from the canonical store.</p>
      </article>
    );
  }

  const all = metric === "all";
  const effectiveFormat = all ? "json" : format;
  const params = new URLSearchParams({ metric, format: effectiveFormat });
  if (window !== "all") params.set("days", window);
  const href = `/api/export?${params.toString()}`;
  const selected = available.find((m) => m.metric === metric);

  return (
    <article className="card">
      <h2>Export</h2>
      <p className="rel-sub">
        Your data, out — CSV or JSON, straight from the canonical store on this host.
      </p>
      <div className="filter-bar" role="group" aria-label="Export controls">
        <label className="filter-field">
          <span className="filter-label">Metric</span>
          <select className="filter-select" value={metric} onChange={(e) => setMetric(e.target.value)}>
            {available.map((m) => (
              <option key={m.metric} value={m.metric}>
                {m.display_name}
              </option>
            ))}
            <option value="all">Everything (JSON)</option>
          </select>
        </label>
        <label className="filter-field">
          <span className="filter-label">Format</span>
          <select
            className="filter-select"
            value={effectiveFormat}
            disabled={all}
            onChange={(e) => setFormat(e.target.value === "json" ? "json" : "csv")}
          >
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
        </label>
        <label className="filter-field">
          <span className="filter-label">Window</span>
          <select className="filter-select" value={window} onChange={(e) => setWindow(e.target.value)}>
            {WINDOWS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
        </label>
        <a className="btn export-btn" href={href} download>
          Download
        </a>
      </div>
      <div className="export-meta mono">
        {available.length === 0
          ? "nothing exportable yet — sync some data first"
          : selected
            ? `${selected.count.toLocaleString()} rows on host · ${dayLabel(selected.oldest)} → ${dayLabel(selected.newest)}`
            : `${available.length} metrics · one JSON object, capped at 100k rows per metric`}
      </div>
    </article>
  );
}
