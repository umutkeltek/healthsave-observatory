import type { Metadata } from "next";
import { Suspense } from "react";

import { COMPARE_RANGES, CompareSection } from "../components/sections/CompareSections";
import { CardSkeleton, LeadSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Compare · HealthSave" };
export const dynamic = "force-dynamic";

type SearchParams = { [key: string]: string | string[] | undefined };

const one = (value: string | string[] | undefined): string =>
  Array.isArray(value) ? (value[0] ?? "") : (value ?? "");

// Intro paints immediately; comparison streams in behind it.
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
      <div className="prov-intro route-note">
        <p>
          Choose a metric and comparison mode. Both sides stay visible so differences remain
          inspectable instead of being blended into one number.
        </p>
      </div>

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
