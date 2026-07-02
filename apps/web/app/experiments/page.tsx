import type { Metadata } from "next";
import { Suspense } from "react";

import { ExperimentsListSection } from "../components/sections/ExperimentsSections";
import { LeadSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Experiments · HealthSave" };
export const dynamic = "force-dynamic";

export default function ExperimentsPage() {
  return (
    <Suspense fallback={<LeadSkeleton />}>
      <ExperimentsListSection />
    </Suspense>
  );
}
