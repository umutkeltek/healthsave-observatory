// Renders a saved Explore panel as a compact card on the Today dashboard.
// Fetches the series data server-side and draws a mini sparkline for each
// metric. Used by Today's saved-panels section (app/page.tsx).

import { BaselineRibbon } from "./BaselineRibbon";
import { deserializeExploreState, fetchRange, filterWindow } from "../lib/explore";
import { safeSeriesMany } from "../lib/load";
import { removeSavedPanelAction } from "../lib/actions";

type Props = {
  id: string;
  label: string;
  encodedState: string;
  // Shown when the saved view holds no panels (dict.prefs.emptySaved).
  emptyNote: string;
};

async function removePanel(id: string) {
  "use server";
  await removeSavedPanelAction(id);
}

export async function ExplorePanelCard({ id, label, encodedState, emptyNote }: Props) {
  const state = deserializeExploreState(encodedState);
  // Collect all unique metrics across all panels
  const metricIds = state ? [...new Set(state.panels.flatMap((p) => p.metrics))] : [];
  // A view with nothing to draw still shows, so it can be removed: rendering
  // nothing left an invisible card holding one of Today's slots.
  if (!state || metricIds.length === 0) {
    return (
      <article className="card explore-panel-card">
        <div className="card-title">
          <span>{label}</span>
          <RemoveSavedPanel id={id} label={label} />
        </div>
        <p className="empty">{emptyNote}</p>
      </article>
    );
  }

  const seriesMap = await safeSeriesMany(metricIds, fetchRange(state));

  return (
    <article className="card explore-panel-card">
      <div className="card-title">
        <span>{label}</span>
        <RemoveSavedPanel id={id} label={label} />
      </div>

      <div className="explore-panel-metrics">
        {state.panels.map((panel, pi) =>
          panel.metrics.map((metricId) => {
            const series = seriesMap.get(metricId);
            const points = filterWindow(series?.points ?? [], state.from, state.to);
            const values = points.filter((p): p is typeof p & { value: number } => p.value !== null);
            const numeric = values.map((p) => p.value);
            const hoverLabels = values.map((p) =>
              new Date(p.t).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
            );

            return (
              <div key={`${pi}-${metricId}`} className="explore-panel-metric">
                <span className="explore-panel-metric-name mono">
                  {series?.metric?.display_name ?? metricId}
                </span>
                {numeric.length >= 3 ? (
                  <BaselineRibbon
                    values={numeric}
                    height={64}
                    hoverLabels={hoverLabels}
                    ariaLabel={`${metricId} — ${label}`}
                  />
                ) : (
                  <p className="empty">Not enough data.</p>
                )}
              </div>
            );
          }),
        )}
      </div>
    </article>
  );
}

function RemoveSavedPanel({ id, label }: { id: string; label: string }) {
  return (
    <form action={removePanel.bind(null, id)}>
      <button
        type="submit"
        className="btn-ghost panel-remove-btn"
        aria-label={`Remove "${label}" from Today`}
        style={{ fontSize: "0.8rem" }}
      >
        Remove
      </button>
    </form>
  );
}
