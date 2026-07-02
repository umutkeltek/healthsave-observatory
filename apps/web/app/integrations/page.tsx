import type { Metadata } from "next";
import { Suspense } from "react";

import { IntegrationsSection } from "../components/sections/IntegrationsSections";
import { GridSkeleton } from "../components/Skeletons";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Integrations · HealthSave Observatory" };

// The intro paints immediately; the live integration states stream in behind
// it (data fetching lives in components/sections/IntegrationsSections.tsx).
export default function IntegrationsPage() {
  return (
    <>
      <section className="lead">
        <p className="lib-intro">
          Everything that feeds this Observatory or receives from it — with live state. Sources
          push data in; destinations are where your data goes <em>only</em> when you route it.
        </p>
      </section>

      <Suspense fallback={<GridSkeleton count={4} />}>
        <IntegrationsSection />
      </Suspense>
    </>
  );
}
