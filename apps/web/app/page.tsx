import { Suspense } from "react";

import {
GoalSection,
HeroSection,
ReadinessSection,
SignalsSection,
TodayStorySection,
VaultSection,
} from "./components/sections/TodaySections";
import { CardSkeleton, GridSkeleton, HeroSkeleton, LeadSkeleton, RowSkeleton } from "./components/Skeletons";

export const revalidate = 30;

export default function Home() {
return (
<div className="today-page">
<Suspense fallback={<HeroSkeleton />}>
<HeroSection />
</Suspense>

      <Suspense fallback={null}>
        <GoalSection />
      </Suspense>

<Suspense fallback={<RowSkeleton />}>
<TodayStorySection />
</Suspense>

      <Suspense fallback={<GridSkeleton />}>
        <SignalsSection />
      </Suspense>

      <div className="row-2 today-proof-row">
        <Suspense fallback={<CardSkeleton />}>
          <VaultSection />
        </Suspense>
        <Suspense fallback={<LeadSkeleton />}>
          <ReadinessSection />
        </Suspense>
      </div>

<footer className="foot">HealthSave Observatory · canonical observations · local-first</footer>
</div>
);
}
