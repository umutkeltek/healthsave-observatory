import { Suspense } from "react";
import { DEFAULT_TODAY_METRICS } from "./lib/todayPresentation";
import { TodayExploration } from "./components/TodayExploration";

import {
  GoalSection,
  HeroSection,
  ReadinessSection,
  TodayStorySection,
  VaultSection,
} from "./components/sections/TodaySections";
import { DashboardCustomizer } from "./components/DashboardCustomizer";
import { ExplorePanelCard } from "./components/ExplorePanelCard";
import {
  CardSkeleton,
  GridSkeleton,
  HeroSkeleton,
  LeadSkeleton,
  RowSkeleton,
} from "./components/Skeletons";
import { getDictionary } from "./lib/i18n";
import { getLocale } from "./lib/i18n.server";
import {
  getDashboardSections,
  getPinnedMetrics,
  getSavedPanels,
} from "./lib/prefs";

export const revalidate = 30;

// Today reads the user's dashboard cookie to decide which sections to show.
// The hero is always present — it's the anchor of every template. Everything
// else is optional, so a user who only wants recovery + sleep can hide the
// signal grid, findings panel, and vault entirely.
export default async function Home() {
  const sections = await getDashboardSections();
  const savedPanels = await getSavedPanels();
  const pinnedMetrics = await getPinnedMetrics();
  const dict = getDictionary(await getLocale());

  return (
    <TodayExploration
      enabled={sections.story}
      metricIds={
        pinnedMetrics.length
          ? pinnedMetrics
          : DEFAULT_TODAY_METRICS.map((metric) => metric.id)
      }
      initialMetricId={pinnedMetrics[0] ?? "vital.hrv_sdnn"}
    >
      <div className="today-page">
        <Suspense fallback={<HeroSkeleton showSignals={sections.signals} />}>
          <HeroSection showSignals={sections.signals} />
        </Suspense>

        {sections.goal && (
          <Suspense fallback={null}>
            <GoalSection />
          </Suspense>
        )}

        {sections.story && (
          <Suspense fallback={<RowSkeleton />}>
            <TodayStorySection />
          </Suspense>
        )}

        {sections.savedPanels && savedPanels.length > 0 && (
          <Suspense fallback={<GridSkeleton />}>
            <div className="today-grid">
              {savedPanels.map((panel) => (
                <div key={panel.id} className="col-6">
                  <ExplorePanelCard
                    id={panel.id}
                    label={panel.label}
                    encodedState={panel.state}
                  />
                </div>
              ))}
            </div>
          </Suspense>
        )}

        {(sections.vault || sections.readiness) && (
          <div className="row-2 today-proof-row">
            {sections.vault && (
              <Suspense fallback={<CardSkeleton />}>
                <details className="today-disclosure">
                  <summary>
                    Data privacy & sharing<span>View details</span>
                  </summary>
                  <VaultSection />
                </details>
              </Suspense>
            )}
            {sections.readiness && (
              <Suspense fallback={<LeadSkeleton />}>
                <details className="today-disclosure">
                  <summary>
                    Data coverage<span>View details</span>
                  </summary>
                  <ReadinessSection />
                </details>
              </Suspense>
            )}
          </div>
        )}

        <DashboardCustomizer sections={sections} />

        <footer className="foot">{dict.chrome.footer}</footer>
      </div>
    </TodayExploration>
  );
}
