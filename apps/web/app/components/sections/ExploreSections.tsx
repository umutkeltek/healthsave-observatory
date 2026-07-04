// The Explore dashboard body (server component). Reads the parsed dashboard
// state, fetches each panel's metric series once (deduped), and renders each
// panel with the shared grain/stat applied via the pure analytics engine. The
// interactive bits are client islands (ExploreControls / PanelToolbar); the
// charts are server-rendered and re-run whenever the URL state changes.

import { bucketBy, dayOfWeekPivot, hrZoneHistogram, weekHourPivot, type Stat } from "../../lib/analytics";
import type { SeriesPoint } from "../../lib/api";
import { normalize, type ExplorePanel, type ExploreState, type GrainOpt } from "../../lib/explore";
import { safeMetrics, safeSeries } from "../../lib/load";
import { DayOfWeekChart } from "../DayOfWeekChart";
import { ExploreControls, PanelToolbar, type MetricOpt } from "../ExploreControls";
import { HeatmapChart } from "../HeatmapChart";
import { MultiSeriesChart, type ChartSeries } from "../MultiSeriesChart";
import { ZoneBar } from "../ZoneBar";

// Numeric values for a metric under the current grain/stat. "raw" keeps every
// point; the others bucket-and-reduce (Grafana time_bucket + agg).
function metricValues(points: SeriesPoint[], grain: GrainOpt, stat: Stat): number[] {
  if (grain === "raw") return points.map((p) => p.value).filter((v): v is number => v !== null);
  return bucketBy(points, grain, stat).map((b) => b.value);
}

function PanelChart({
  panel,
  state,
  pointsById,
  nameById,
  unitById,
}: {
  panel: ExplorePanel;
  state: ExploreState;
  pointsById: Map<string, SeriesPoint[]>;
  nameById: Map<string, string>;
  unitById: Map<string, string>;
}) {
  const { grain, stat } = state;

  if (panel.chart === "line") {
    const overlay = panel.metrics.length > 1;
    const series: ChartSeries[] = panel.metrics.map((id) => {
      const values = metricValues(pointsById.get(id) ?? [], grain, stat);
      // Overlaid metrics are normalized so different units share one axis
      // honestly (each on its own scale); a single metric keeps real values.
      return { label: nameById.get(id) ?? id, values: overlay ? normalize(values) : values };
    });
    return (
      <>
        <MultiSeriesChart series={series} />
        {overlay && <p className="panel-note">Overlaid signals are normalized to their own 0–1 range.</p>}
      </>
    );
  }

  const primary = panel.metrics[0];
  const pts = pointsById.get(primary) ?? [];
  const unit = unitById.get(primary) ?? "";
  if (panel.chart === "heatmap") return <HeatmapChart cells={weekHourPivot(pts, stat)} unit={unit} />;
  if (panel.chart === "weekday") return <DayOfWeekChart cells={dayOfWeekPivot(pts, stat)} unit={unit} />;
  return <ZoneBar zones={hrZoneHistogram(pts)} />;
}

export async function ExploreSections({ state }: { state: ExploreState }) {
  const metrics = (await safeMetrics()) ?? [];
  const metricOpts: MetricOpt[] = metrics.map((m) => ({
    id: m.id,
    display_name: m.display_name,
    category: m.category,
  }));
  const nameById = new Map(metrics.map((m) => [m.id, m.display_name] as const));
  const unitById = new Map(metrics.map((m) => [m.id, m.canonical_unit ?? ""] as const));

  const neededIds = [...new Set(state.panels.flatMap((p) => p.metrics))];
  const seriesEntries = await Promise.all(
    neededIds.map(async (id) => [id, (await safeSeries(id, state.range))?.points ?? []] as const),
  );
  const pointsById = new Map(seriesEntries);

  return (
    <>
      <ExploreControls state={state} metrics={metricOpts} />
      {state.panels.length === 0 ? (
        <p className="empty">No panels yet — add a signal above to start building your view.</p>
      ) : (
        <div className="explore-grid">
          {state.panels.map((panel, i) => (
            <article className="card explore-panel" key={`${i}-${panel.chart}-${panel.metrics.join(",")}`}>
              <PanelToolbar state={state} index={i} metrics={metricOpts} />
              <PanelChart
                panel={panel}
                state={state}
                pointsById={pointsById}
                nameById={nameById}
                unitById={unitById}
              />
            </article>
          ))}
        </div>
      )}
    </>
  );
}
