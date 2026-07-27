import type { Metadata } from "next";
import { Suspense } from "react";

import { ExperimentsListSection } from "../components/sections/ExperimentsSections";
import { LeadSkeleton } from "../components/Skeletons";
import { parseExperimentPrefill } from "../lib/experimentPrefill";

export const metadata: Metadata = { title: "Experiments · HealthSave" };
export const revalidate = 30;

export default async function ExperimentsPage({
  searchParams,
}: {
  // Read-only prefill from a finding card's "propose experiment" CTA
  // (/experiments?lever=..&outcome=..). No new write path.
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const prefill = parseExperimentPrefill(await searchParams);
  return (
    <Suspense fallback={<LeadSkeleton />}>
      <ExperimentsListSection prefill={prefill} />
    </Suspense>
  );
}
