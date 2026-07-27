import type { Metadata } from "next";
import { Suspense } from "react";

import { IntelligenceSection } from "../components/sections/IntelligenceSections";
import { CardSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Intelligence · HealthSave" };
export const revalidate = 30;

// The topbar owns the page title; the settings surface streams in behind it.
export default function IntelligencePage() {
  return (
    <Suspense
      fallback={
        <>
          <CardSkeleton />
          <CardSkeleton />
        </>
      }
    >
      <IntelligenceSection />
    </Suspense>
  );
}
