import { Suspense } from "react";

import {
  ExperimentsSection,
  HeroSection,
  InsightsSection,
  ReadinessSection,
  SignalsSection,
  VaultSection,
} from "./components/sections/TodaySections";
import { CardSkeleton, GridSkeleton, HeroSkeleton, LeadSkeleton, RowSkeleton } from "./components/Skeletons";

// Always render fresh — this is a live dashboard, not a static page.
export const dynamic = "force-dynamic";

// The page awaits nothing: every section streams in through its own Suspense
// boundary (data fetching lives in components/sections/TodaySections.tsx).
// First byte is the shell + skeletons; the slowest read fills in last.
export default function Home() {
  return (
    <>
      <div className="today-grid">
        <Suspense fallback={<HeroSkeleton />}>
          <HeroSection />
        </Suspense>
        <Suspense fallback={<CardSkeleton className="col-4" />}>
          <VaultSection />
        </Suspense>
      </div>

      <Suspense fallback={<RowSkeleton />}>
        <InsightsSection />
      </Suspense>

      <Suspense fallback={<LeadSkeleton />}>
        <ExperimentsSection />
      </Suspense>

      <Suspense fallback={<GridSkeleton />}>
        <SignalsSection />
      </Suspense>

      <Suspense fallback={<LeadSkeleton />}>
        <ReadinessSection />
      </Suspense>

      <footer className="foot">HealthSave Observatory · canonical observations · local-first</footer>
    </>
  );
}
