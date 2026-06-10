import type { Metadata } from "next";

import { LibraryBrowser, type LibraryRow } from "../components/LibraryBrowser";
import { agoLabel, safeMetrics, safeReadiness } from "../lib/load";
import { getPinnedMetrics } from "../lib/prefs";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Library · HealthSave Observatory" };

// The whole registry (~190 canonical metrics) joined with per-metric readiness
// stats — every signal the system can hold, browsable and pinnable. No series
// fan-out here (that would recreate the old N+1 page load); sparklines live on
// the detail page.
export default async function LibraryPage() {
  const [metrics, readiness, pinned] = await Promise.all([
    safeMetrics(),
    safeReadiness(),
    getPinnedMetrics(),
  ]);

  if (!metrics) {
    return (
      <section className="lead">
        <div className="card">
          <h2>Library</h2>
          <p className="empty">Backend unreachable — start HealthSave Observatory to browse your signals.</p>
        </div>
      </section>
    );
  }

  const stats = new Map(readiness?.metrics.map((m) => [m.metric_id, m]) ?? []);
  const pinnedSet = new Set(pinned);

  const rows: LibraryRow[] = metrics.map((metric) => {
    const stat = stats.get(metric.id);
    return {
      id: metric.id,
      name: metric.display_name,
      category: metric.category,
      unit: metric.canonical_unit,
      valueType: metric.value_type,
      count: stat?.observation_count ?? 0,
      days: stat?.days_with_data ?? 0,
      lastAt: stat?.last_observation_at ?? null,
      lastLabel: agoLabel(stat?.last_observation_at),
      analyzable: Object.values(stat?.analyzable ?? {}).some((g) => g.is_sufficient),
      pinned: pinnedSet.has(metric.id),
    };
  });

  const categories = [...new Set(rows.map((r) => r.category))].sort();
  const withData = rows.filter((r) => r.count > 0).length;
  const statsAvailable = readiness !== null;

  return (
    <>
      <section className="lead">
        <p className="lib-intro">
          {statsAvailable ? (
            <>
              <strong>{withData}</strong> of <strong>{rows.length}</strong> canonical signals carry
              your data.
            </>
          ) : (
            <>
              <strong>{rows.length}</strong> canonical signals in the registry — per-signal stats are
              unavailable right now (readiness endpoint unreachable).
            </>
          )}{" "}
          Pin any signal to put it on the Today grid; open one for its baseline, sources, and
          caveats.
        </p>
      </section>
      <LibraryBrowser rows={rows} categories={categories} defaultWithData={statsAvailable} />
    </>
  );
}
