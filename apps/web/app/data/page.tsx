import type { Metadata } from "next";
import { Suspense } from "react";

import {
  type DataFilters,
  DataExportSection,
  DataReadinessSection,
  ExplorerSection,
  RANGES,
} from "../components/sections/DataSections";
import { CardSkeleton, GridSkeleton, LeadSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Data · HealthSave" };
export const dynamic = "force-dynamic";

type SearchParams = { [key: string]: string | string[] | undefined };
function one(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

// The page awaits only its search params (no network); every data read streams
// in through its own Suspense boundary in components/sections/DataSections.tsx.
export default async function DataPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const filters: DataFilters = {
    metricSel: one(sp.metric),
    categorySel: one(sp.category),
    sourceSel: one(sp.source),
    deviceSel: one(sp.device),
    sortSel: one(sp.sort),
    range: RANGES.includes(one(sp.range)) ? one(sp.range) : "7d",
  };
  // Re-mount the explorer when filters change so stale cards never linger
  // behind a slow re-fetch — the skeleton is the honest in-between state.
  const explorerKey = JSON.stringify(filters);

  return (
    <>
      <Suspense
        key={explorerKey}
        fallback={
          <>
            <CardSkeleton />
            <GridSkeleton />
          </>
        }
      >
        <ExplorerSection filters={filters} />
      </Suspense>

      <Suspense fallback={<LeadSkeleton />}>
        <DataReadinessSection />
      </Suspense>

      <Suspense fallback={<LeadSkeleton />}>
        <DataExportSection />
      </Suspense>
    </>
  );
}
