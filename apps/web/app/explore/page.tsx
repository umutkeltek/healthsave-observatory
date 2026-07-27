import type { Metadata } from "next";
import { Suspense } from "react";

import { ExploreSections } from "../components/sections/ExploreSections";
import { CardSkeleton } from "../components/Skeletons";
import { encodeExploreState, parseExploreState } from "../lib/explore";

export const metadata: Metadata = { title: "Explore · HealthSave" };
export const revalidate = 30;

type SearchParams = { [key: string]: string | string[] | undefined };

const one = (value: string | string[] | undefined): string =>
  Array.isArray(value) ? (value[0] ?? "") : (value ?? "");

// The composable dashboard: build your own panels over any signals, choose the
// time bucket + aggregate, and overlay metrics. State lives entirely in the URL,
// so a view is shareable and deep-linkable.
export default async function ExplorePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const state = parseExploreState({
    range: one(sp.range),
    grain: one(sp.grain),
    stat: one(sp.stat),
    from: one(sp.from),
    to: one(sp.to),
    panels: one(sp.panels),
  });

  return (
    <>
      <Suspense
        key={encodeExploreState(state)}
        fallback={
          <>
            <CardSkeleton />
            <CardSkeleton />
          </>
        }
      >
        <ExploreSections state={state} />
      </Suspense>
    </>
  );
}
