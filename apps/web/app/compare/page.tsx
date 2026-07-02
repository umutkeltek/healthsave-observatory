import type { Metadata } from "next";
import { Suspense } from "react";

import { COMPARE_RANGES, CompareSection } from "../components/sections/CompareSections";
import { CardSkeleton, LeadSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Compare · HealthSave" };
export const dynamic = "force-dynamic";

type SearchParams = { [key: string]: string | string[] | undefined };
const one = (v: string | string[] | undefined): string => (Array.isArray(v) ? (v[0] ?? "") : (v ?? ""));

// The intro paints immediately; the comparison streams in behind it (data
// fetching lives in components/sections/CompareSections.tsx).
export default async function ComparePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const sp = await searchParams;
  const metricSel = one(sp.metric);
  const modeSel = one(sp.mode);
  const mode = modeSel === "source" || modeSel === "device" ? modeSel : "period";
  const range = COMPARE_RANGES.includes(one(sp.range)) ? one(sp.range) : "30d";

  return (
    <>
      <div className="prov-intro">
        <h2>Compare</h2>
        <p>
          Period vs previous, or source vs source — both readings are kept, never merged into one number.
          The gap is the signal, not a blended figure.
        </p>
      </div>

      {/* Re-mount on selection change so a stale comparison never lingers behind a slow re-fetch. */}
      <Suspense
        key={`${metricSel}|${mode}|${range}`}
        fallback={
          <>
            <CardSkeleton />
            <LeadSkeleton />
          </>
        }
      >
        <CompareSection metricSel={metricSel} mode={mode} range={range} />
      </Suspense>
    </>
  );
}
