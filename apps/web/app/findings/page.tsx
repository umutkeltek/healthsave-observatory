import type { Metadata } from "next";
import { Suspense } from "react";

import { BriefSection, FindingsEvidenceSection } from "../components/sections/FindingsSections";
import { LeadSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Findings · HealthSave" };
export const revalidate = 30;

// The page awaits nothing: each card streams in through its own Suspense
// boundary (data fetching lives in components/sections/FindingsSections.tsx).
export default function FindingsPage() {
  return (
    <>
      <Suspense fallback={<LeadSkeleton />}>
        <BriefSection />
      </Suspense>
      <Suspense fallback={<LeadSkeleton />}>
        <FindingsEvidenceSection />
      </Suspense>
    </>
  );
}
