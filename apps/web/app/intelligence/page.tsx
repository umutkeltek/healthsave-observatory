import type { Metadata } from "next";
import { Suspense } from "react";

import { IntelligenceSection } from "../components/sections/IntelligenceSections";
import { CardSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Intelligence · HealthSave" };
export const dynamic = "force-dynamic";

// The header paints immediately; the settings form streams in behind it.
export default function IntelligencePage() {
  return (
    <section className="lead">
      <header className="intel-head">
        <h1 className="intel-title">Intelligence</h1>
        <p className="intel-tag">
          Choose how your briefs are written — and exactly what, if anything, leaves your host.
        </p>
      </header>
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
    </section>
  );
}
