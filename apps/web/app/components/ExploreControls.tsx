"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import {
  CHART_KINDS,
  EXPLORE_GRAINS,
  EXPLORE_RANGE_LABELS,
  EXPLORE_RANGES,
  EXPLORE_STATS,
  encodeExploreState,
  type ChartKind,
  type ExplorePanel,
  type ExploreState,
} from "../lib/explore";
import { saveExplorePanelAction } from "../lib/actions";

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

type SavedView = { name: string; qs: string };
const VIEWS_KEY = "explore_views";

// Saved views persist in localStorage (per-browser; fine for a single-user
// self-hosted product). Each stores the current URL query, so opening one just
// navigates there — the whole dashboard is already URL-encoded.
function SavedViews({ current }: { current: string }) {
  const router = useRouter();
  const [views, setViews] = useState<SavedView[]>([]);
  const [name, setName] = useState("");

  useEffect(() => {
    try {
      const raw = localStorage.getItem(VIEWS_KEY);
      if (raw) setViews(JSON.parse(raw));
    } catch {
      // ignore malformed storage
    }
  }, []);

  const persist = (next: SavedView[]) => {
    setViews(next);
    try {
      localStorage.setItem(VIEWS_KEY, JSON.stringify(next));
    } catch {
      // storage may be unavailable (private mode) — the in-memory list still works
    }
  };
  const save = () => {
    const n = name.trim();
    if (!n) return;
    persist([...views.filter((v) => v.name !== n), { name: n, qs: current }]);
    setName("");
  };
  const remove = (n: string) => persist(views.filter((v) => v.name !== n));

  return (
    <div className="saved-views">
      <span className="saved-views-label">Views</span>
      {views.map((v) => (
        <span key={v.name} className="panel-chip saved-view-chip">
          <button
            type="button"
            className="saved-view-open"
            onClick={() => router.push(`/explore?${v.qs}`)}
          >
            {v.name}
          </button>
          <button
            type="button"
            className="panel-chip-x"
            aria-label={`Delete view ${v.name}`}
            onClick={() => remove(v.name)}
          >
            ×
          </button>
        </span>
      ))}
      <input
        className="filter-select saved-view-input"
        placeholder="Save this view as…"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
        }}
      />
      <button type="button" className="btn-ghost panel-remove-btn" onClick={save} disabled={!name.trim()}>
        Save
      </button>
    </div>
  );
}

// Save-to-Today: persists the current explore dashboard as a compact card on
// the Today page. Uses a server action (cookie-backed, revalidates /).
function SaveToToday({ current }: { current: string }) {
  const [, startTransition] = useTransition();
  const [label, setLabel] = useState("");
  const [saved, setSaved] = useState(false);

  const save = () => {
    const name = label.trim();
    if (!name) return;
    startTransition(async () => {
      const result = await saveExplorePanelAction(current, name);
      if (result.ok) {
        setSaved(true);
        setLabel("");
        setTimeout(() => setSaved(false), 2000);
      }
    });
  };

  return (
    <div className="saved-views" style={{ marginTop: 8 }}>
      <span className="saved-views-label">Pin to Today</span>
      {saved ? (
        <span className="panel-chip" style={{ color: "var(--up)", borderColor: "var(--up)" }}>
          ✓ Saved!
        </span>
      ) : (
        <>
          <input
            className="filter-select saved-view-input"
            placeholder="Label this view…"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") save();
            }}
          />
          <button
            type="button"
            className="btn-ghost panel-remove-btn"
            onClick={save}
            disabled={!label.trim()}
          >
            Pin
          </button>
        </>
      )}
    </div>
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
          disabled={Boolean(state.from || state.to)}
          title={state.from || state.to ? "Clear the custom dates to use a preset" : undefined}
          onChange={(e) => set({ range: e.target.value })}
        >
          {EXPLORE_RANGES.map((r) => (
            <option key={r} value={r}>
              {EXPLORE_RANGE_LABELS[r]}
            </option>
          ))}
        </select>
      </div>
      <div className="explore-control">
        <label>From</label>
        <input
          type="date"
          className="filter-select"
          value={state.from ?? ""}
          max={state.to || undefined}
          onChange={(e) => set({ from: e.target.value || undefined })}
        />
      </div>
      <div className="explore-control">
        <label>To</label>
        <input
          type="date"
          className="filter-select"
          value={state.to ?? ""}
          min={state.from || undefined}
          onChange={(e) => set({ to: e.target.value || undefined })}
        />
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
      <SavedViews current={encodeExploreState(state)} />

      {/* Save-to-Today: persists this dashboard as a compact card on / */}
      <SaveToToday current={encodeExploreState(state)} />
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
  const move = (dir: -1 | 1) => {
    const j = index + dir;
    if (j < 0 || j >= state.panels.length) return;
    const panels = [...state.panels];
    [panels[index], panels[j]] = [panels[j], panels[index]];
    nav({ ...state, panels });
  };
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
        <button
          type="button"
          className="btn-ghost panel-move"
          onClick={() => move(-1)}
          disabled={index === 0}
          aria-label="Move panel earlier"
        >
          ←
        </button>
        <button
          type="button"
          className="btn-ghost panel-move"
          onClick={() => move(1)}
          disabled={index === state.panels.length - 1}
          aria-label="Move panel later"
        >
          →
        </button>
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
