// The Explore dashboard body (server component). Reads the parsed dashboard
// state, fetches each panel's metric series once (deduped), and renders each
// panel with the shared grain/stat applied via the pure analytics engine. The
// interactive bits are client islands (ExploreControls / PanelToolbar); the
// charts are server-rendered and re-run whenever the URL state changes.

import { timeBasisLabel, UTC_TIME_BASIS } from "../../lib/analyticalTime";
import { bucketBy, dayOfWeekPivot, hrZoneHistogram, weekHourPivot, type Stat } from "../../lib/analytics";
import type { SeriesPoint } from "../../lib/api";
import {
  fetchRange,
  filterWindow,
  normalize,
  type ExplorePanel,
  type ExploreState,
  type GrainOpt,
} from "../../lib/explore";
import { safeAnalyticalTime, safeMetrics, safeSeries } from "../../lib/load";
import { DayOfWeekChart } from "../DayOfWeekChart";
import { ExploreControls, PanelToolbar, type MetricOpt } from "../ExploreControls";
import { HeatmapChart } from "../HeatmapChart";
import { MultiSeriesChart, type ChartSeries } from "../MultiSeriesChart";
import { ZoneBar } from "../ZoneBar";

// Honest data-density hint: tells the user how many samples their dashboard
// actually pulled and the calendar span. "All time" hides nothing — the user
// sees the full history's earliest/latest stamp. "30d" with only 6 days of
// data is honest too: the user can see why their chart looks sparse.
type Density = {
  totalPoints: number;
  metricsWithData: number;
  metricsTotal: number;
  earliest: string | null;
  latest: string | null;
};

function computeDensity(
  pointArrays: { t: string; value: number | null }[][],
): Density | null {
  let total = 0;
  let metricsWithData = 0;
  let earliest: string | null = null;
  let latest: string | null = null;
  for (const points of pointArrays) {
    const valued = points.filter((p): p is { t: string; value: number } => p.value !== null);
    if (valued.length > 0) metricsWithData += 1;
    total += valued.length;
    for (const p of valued) {
      if (!earliest || p.t < earliest) earliest = p.t;
      if (!latest || p.t > latest) latest = p.t;
    }
  }
  const metricsTotal = pointArrays.length;
  if (total === 0) return null;
  return { totalPoints: total, metricsWithData, metricsTotal, earliest, latest };
}

function DataDensityHint({ density, range }: { density: Density; range: string }) {
  const fmt = (iso: string): string => {
    const d = new Date(iso);
    return Number.isFinite(d.getTime())
      ? d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
      : iso;
  };
  return (
    <p className="explore-density mono">
      {density.totalPoints.toLocaleString()} samples across{" "}
      {density.metricsWithData}/{density.metricsTotal} signals
      {density.earliest && density.latest && (
        <>
          {" · "}
          {fmt(density.earliest)} → {fmt(density.latest)}
          {range === "all" ? " (entire history)" : ""}
        </>
      )}
    </p>
  );
}

// Timestamped values under the current grain/stat. Keeping the timestamp with
// every value prevents irregular samples from being drawn at equal spacing.
function metricPoints(
  points: SeriesPoint[],
  grain: GrainOpt,
  stat: Stat,
  timeBasis: typeof UTC_TIME_BASIS,
): { t: string; value: number }[] {
  if (grain === "raw") {
    return points
      .filter((point): point is SeriesPoint & { value: number } => point.value !== null)
      .map((point) => ({ t: point.t, value: point.value }));
  }
  return bucketBy(points, grain, stat, timeBasis).map((bucket) => ({ t: bucket.t, value: bucket.value }));
}

function PanelChart({
  panel,
  state,
  pointsById,
  nameById,
  unitById,
  timeBasis,
}: {
  panel: ExplorePanel;
  state: ExploreState;
  pointsById: Map<string, SeriesPoint[]>;
  nameById: Map<string, string>;
  unitById: Map<string, string>;
  timeBasis: typeof UTC_TIME_BASIS;
}) {
  const { grain, stat } = state;

  if (panel.chart === "line") {
    const overlay = panel.metrics.length > 1;
    const series: ChartSeries[] = panel.metrics.map((id) => {
      const points = metricPoints(pointsById.get(id) ?? [], grain, stat, timeBasis);
      // Overlaid metrics are normalized so different units share one axis
      // honestly (each on its own scale); timestamps remain unchanged.
      const values = points.map((point) => point.value);
      const normalized = overlay ? normalize(values) : values;
      return {
        label: nameById.get(id) ?? id,
        points: points.map((point, index) => ({ ...point, value: normalized[index] })),
      };
    });
    const unit = overlay ? null : unitById.get(panel.metrics[0]) || null;
    return (
      <>
        <MultiSeriesChart series={series} unit={unit} />
        {overlay && <p className="panel-note">Overlaid signals are normalized to their own 0–1 range.</p>}
      </>
    );
  }

  const primary = panel.metrics[0];
  const pts = pointsById.get(primary) ?? [];
  const unit = unitById.get(primary) ?? "";
  if (panel.chart === "heatmap") return <><p className="meta">{timeBasisLabel(timeBasis)}</p><HeatmapChart cells={weekHourPivot(pts, stat, timeBasis)} unit={unit} /></>;
  if (panel.chart === "weekday") return <><p className="meta">{timeBasisLabel(timeBasis)}</p><DayOfWeekChart cells={dayOfWeekPivot(pts, stat, timeBasis)} unit={unit} /></>;
  return <ZoneBar zones={hrZoneHistogram(pts)} />;
}

export async function ExploreSections({ state }: { state: ExploreState }) {
  const [loadedMetrics, analyticalTime] = await Promise.all([safeMetrics(), safeAnalyticalTime()]);
  const metrics = loadedMetrics ?? [];
  const timeBasis = analyticalTime ?? UTC_TIME_BASIS;
  const metricOpts: MetricOpt[] = metrics.map((m) => ({
    id: m.id,
    display_name: m.display_name,
    category: m.category,
  }));
  const nameById = new Map(metrics.map((m) => [m.id, m.display_name] as const));
  const unitById = new Map(metrics.map((m) => [m.id, m.canonical_unit ?? ""] as const));

  const range = fetchRange(state);
  const neededIds = [...new Set(state.panels.flatMap((p) => p.metrics))];
  const seriesEntries = await Promise.all(
    neededIds.map(async (id) => {
      const series = await safeSeries(id, range);
      const pts = series?.points ?? [];
      return [id, { points: filterWindow(pts, state.from, state.to), series }] as const;
    }),
  );
  const pointsById = new Map(seriesEntries.map(([id, data]) => [id, data.points]));

  // Honest data-density hint: counts the non-null samples across every panel
  // and reports the actual span of the data we have. "All time" hides the
  // calendar interval; "30d" shows it. Helps users see why a sparse-looking
  // chart is actually their full history.
  const density = computeDensity([...pointsById.values()]);

  return (
    <>
      <ExploreControls state={state} metrics={metricOpts} />
      {density && <DataDensityHint density={density} range={range} />}
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
                timeBasis={timeBasis}
              />
            </article>
          ))}
        </div>
      )}
    </>
  );
}
