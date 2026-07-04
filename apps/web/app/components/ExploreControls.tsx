"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  CHART_KINDS,
  EXPLORE_GRAINS,
  EXPLORE_RANGES,
  EXPLORE_STATS,
  encodeExploreState,
  type ChartKind,
  type ExplorePanel,
  type ExploreState,
} from "../lib/explore";

// Client islands for the Explore dashboard. They hold no data — they read the
// current dashboard from the URL (via the `state` prop the server parsed) and
// write the next dashboard back to the URL. The server component re-fetches and
// re-renders the charts. Same URL-as-state pattern as FilterBar.

export type MetricOpt = { id: string; display_name: string; category: string };

function useExploreNav() {
  const router = useRouter();
  const pathname = usePathname();
  return (next: ExploreState) =>
    router.replace(`${pathname}?${encodeExploreState(next)}`, { scroll: false });
}

function MetricSelect({
  metrics,
  exclude,
  placeholder,
  onPick,
}: {
  metrics: MetricOpt[];
  exclude?: string[];
  placeholder: string;
  onPick: (id: string) => void;
}) {
  const options = metrics.filter((m) => !exclude?.includes(m.id));
  return (
    <select
      className="filter-select"
      value=""
      onChange={(e) => {
        if (e.target.value) onPick(e.target.value);
      }}
      aria-label={placeholder}
    >
      <option value="">{placeholder}</option>
      {options.map((m) => (
        <option key={m.id} value={m.id}>
          {m.display_name}
        </option>
      ))}
    </select>
  );
}

// Global dashboard controls + add-panel.
export function ExploreControls({ state, metrics }: { state: ExploreState; metrics: MetricOpt[] }) {
  const nav = useExploreNav();
  const set = (patch: Partial<ExploreState>) => nav({ ...state, ...patch });
  const addPanel = (metricId: string) =>
    nav({ ...state, panels: [...state.panels, { chart: "line", metrics: [metricId] }] });

  return (
    <div className="explore-controls card">
      <div className="explore-control">
        <label>Range</label>
        <select
          className="filter-select"
          value={state.range}
          onChange={(e) => set({ range: e.target.value })}
        >
          {EXPLORE_RANGES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>
      <div className="explore-control">
        <label>Bucket</label>
        <select
          className="filter-select"
          value={state.grain}
          onChange={(e) => set({ grain: e.target.value as ExploreState["grain"] })}
        >
          {EXPLORE_GRAINS.map((g) => (
            <option key={g.id} value={g.id}>
              {g.label}
            </option>
          ))}
        </select>
      </div>
      <div className="explore-control">
        <label>Aggregate</label>
        <select
          className="filter-select"
          value={state.stat}
          disabled={state.grain === "raw"}
          onChange={(e) => set({ stat: e.target.value as ExploreState["stat"] })}
        >
          {EXPLORE_STATS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      <div className="explore-control explore-control-grow">
        <label>Add panel</label>
        <MetricSelect metrics={metrics} placeholder="Pick a signal…" onPick={addPanel} />
      </div>
    </div>
  );
}

// Per-panel toolbar: chart kind, the metrics on this panel, and remove.
export function PanelToolbar({
  state,
  index,
  metrics,
}: {
  state: ExploreState;
  index: number;
  metrics: MetricOpt[];
}) {
  const nav = useExploreNav();
  const panel = state.panels[index];
  const nameById = new Map(metrics.map((m) => [m.id, m.display_name] as const));

  const update = (p: ExplorePanel) => {
    const panels = [...state.panels];
    panels[index] = p;
    nav({ ...state, panels });
  };
  const removePanel = () => nav({ ...state, panels: state.panels.filter((_, i) => i !== index) });
  const setChart = (chart: ChartKind) => update({ ...panel, chart });
  const addMetric = (id: string) =>
    !panel.metrics.includes(id) && update({ ...panel, metrics: [...panel.metrics, id] });
  const removeMetric = (id: string) =>
    panel.metrics.length > 1 && update({ ...panel, metrics: panel.metrics.filter((m) => m !== id) });

  // Overlay only makes sense for the line chart; the pivot charts read one metric.
  const canOverlay = panel.chart === "line";

  return (
    <div className="panel-toolbar">
      <div className="panel-metrics">
        {panel.metrics.map((id) => (
          <span key={id} className="panel-chip">
            {nameById.get(id) ?? id}
            {panel.metrics.length > 1 && (
              <button
                type="button"
                className="panel-chip-x"
                aria-label={`Remove ${nameById.get(id) ?? id}`}
                onClick={() => removeMetric(id)}
              >
                ×
              </button>
            )}
          </span>
        ))}
        {canOverlay && (
          <MetricSelect
            metrics={metrics}
            exclude={panel.metrics}
            placeholder="+ overlay"
            onPick={addMetric}
          />
        )}
      </div>
      <div className="panel-tools">
        <select
          className="filter-select"
          value={panel.chart}
          onChange={(e) => setChart(e.target.value as ChartKind)}
          aria-label="Chart type"
        >
          {CHART_KINDS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
        <button type="button" className="btn-ghost panel-remove-btn" onClick={removePanel} aria-label="Remove panel">
          Remove
        </button>
      </div>
    </div>
  );
}
