import { Suspense } from "react";

import {
GoalSection,
HeroSection,
ReadinessSection,
SignalsSection,
TodayStorySection,
VaultSection,
} from "./components/sections/TodaySections";
import { DashboardCustomizer } from "./components/DashboardCustomizer";
import { CardSkeleton, GridSkeleton, HeroSkeleton, LeadSkeleton, RowSkeleton } from "./components/Skeletons";
import { getDashboardSections } from "./lib/prefs";

export const revalidate = 30;

// Today reads the user's dashboard cookie to decide which sections to show.
// The hero is always present — it's the anchor of every template. Everything
// else is optional, so a user who only wants recovery + sleep can hide the
// signal grid, findings panel, and vault entirely.
export default async function Home() {
  const sections = await getDashboardSections();

  return (
    <div className="today-page">
      <Suspense fallback={<HeroSkeleton />}>
        <HeroSection />
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

      {sections.signals && (
        <Suspense fallback={<GridSkeleton />}>
          <SignalsSection />
        </Suspense>
      )}

      {(sections.vault || sections.readiness) && (
        <div className="row-2 today-proof-row">
          {sections.vault && (
            <Suspense fallback={<CardSkeleton />}>
              <VaultSection />
            </Suspense>
          )}
          {sections.readiness && (
            <Suspense fallback={<LeadSkeleton />}>
              <ReadinessSection />
            </Suspense>
          )}
        </div>
      )}

      <DashboardCustomizer sections={sections} />

      <footer className="foot">HealthSave Observatory · canonical observations · local-first</footer>
    </div>
  );
}
