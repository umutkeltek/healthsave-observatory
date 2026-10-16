import type { Metadata } from "next";
import { Suspense } from "react";

import {
  BriefSection,
  FindingsEvidenceSection,
} from "../components/sections/FindingsSections";
import { LeadSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Findings · HealthSave" };
export const revalidate = 30;

// Read the selected finding from the URL; evidence data still streams through
// its Suspense boundary in components/sections/FindingsSections.tsx.
export default async function FindingsPage({
  searchParams,
}: {
  searchParams: Promise<{ finding?: string | string[] }>;
}) {
  const { finding } = await searchParams;
  const selectedId = typeof finding === "string" ? finding : undefined;
  return (
    <>
      {!selectedId && (
        <Suspense fallback={<LeadSkeleton />}>
          <BriefSection />
        </Suspense>
      )}
      <Suspense fallback={<LeadSkeleton />}>
        <FindingsEvidenceSection selectedId={selectedId} />
      </Suspense>
    </>
  );
}
