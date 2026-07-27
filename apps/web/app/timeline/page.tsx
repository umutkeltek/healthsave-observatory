import type { Metadata } from "next";
import { Suspense } from "react";

import { MomentForm } from "../components/MomentForm";
import { TimelineView } from "../components/TimelineView";
import { CardSkeleton } from "../components/Skeletons";
import { safeFindings, safeMoments } from "../lib/load";

export const revalidate = 30;
export const metadata: Metadata = { title: "Timeline · HealthSave Observatory" };

async function TimelineSection() {
  const [moments, findings] = await Promise.all([safeMoments(), safeFindings()]);
  return <TimelineView moments={moments ?? []} findings={findings ?? []} />;
}

export default function TimelinePage() {
  return (
    <>
      <Suspense fallback={<CardSkeleton />}>
        <section className="lead">
          <MomentForm />
        </section>
      </Suspense>
      <Suspense fallback={<CardSkeleton />}>
        <section className="lead">
          <TimelineSection />
        </section>
      </Suspense>
    </>
  );
}
