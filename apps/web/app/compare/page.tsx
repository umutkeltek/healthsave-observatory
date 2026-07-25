import type { Metadata } from "next";
import { Suspense } from "react";

import { COMPARE_RANGES, CompareSection } from "../components/sections/CompareSections";
import { CardSkeleton, LeadSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Compare · HealthSave" };
export const dynamic = "force-dynamic";

type SearchParams = { [key: string]: string | string[] | undefined };

const one = (value: string | string[] | undefined): string =>
  Array.isArray(value) ? (value[0] ?? "") : (value ?? "");

// No intro: the topbar title + subtitle already say "Compare periods, sources,
// and devices without losing provenance." Repeating them under the title reads
// as a duplicate. Controls + chart stream in behind the single boundary.
export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const metricSel = one(sp.metric);
  const modeSel = one(sp.mode);
  const mode = modeSel === "source" || modeSel === "device" ? modeSel : "period";
  const range = COMPARE_RANGES.includes(one(sp.range)) ? one(sp.range) : "30d";

  return (
    <>
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
