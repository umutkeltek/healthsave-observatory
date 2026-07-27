import type { Metadata } from "next";
import { Suspense } from "react";

import {
  ComputedRelationshipsSection,
  ExplorePairSection,
  REL_RANGES,
} from "../components/sections/RelationshipsSections";
import { LeadSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Relationships · HealthSave" };
export const revalidate = 30;

const ID_RE = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/;

type SearchParams = { [key: string]: string | string[] | undefined };
const one = (v: string | string[] | undefined): string => (Array.isArray(v) ? (v[0] ?? "") : (v ?? ""));

// The page awaits only its search params; the correlations table and the pair
// explorer stream independently (components/sections/RelationshipsSections.tsx).
export default async function RelationshipsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const range = REL_RANGES.includes(one(sp.range)) ? one(sp.range) : "90d";
  const aId = ID_RE.test(one(sp.a)) ? one(sp.a) : "";
  const bId = ID_RE.test(one(sp.b)) ? one(sp.b) : "";

  return (
    <>
      <Suspense fallback={<LeadSkeleton />}>
        <ComputedRelationshipsSection range={range} />
      </Suspense>
      {/* Re-mount on pair/range change so a stale chart never lingers behind a slow re-fetch. */}
      <Suspense key={`${aId}|${bId}|${range}`} fallback={<LeadSkeleton />}>
        <ExplorePairSection aId={aId} bId={bId} range={range} />
      </Suspense>
    </>
  );
}
