import type { Metadata } from "next";
import { Suspense } from "react";

import { LibrarySection } from "../components/sections/LibrarySections";
import { CardSkeleton, LeadSkeleton } from "../components/Skeletons";

export const revalidate = 30;
export const metadata: Metadata = { title: "Library · HealthSave Observatory" };

export default function LibraryPage() {
  return (
    <Suspense
      fallback={
        <>
          <LeadSkeleton />
          <CardSkeleton />
        </>
      }
    >
      <LibrarySection />
    </Suspense>
  );
}
