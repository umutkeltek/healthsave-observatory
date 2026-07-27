import type { Metadata } from "next";
import { Suspense } from "react";

import { IntegrationsSection } from "../components/sections/IntegrationsSections";
import { GridSkeleton } from "../components/Skeletons";

export const revalidate = 30;
export const metadata: Metadata = { title: "Integrations · HealthSave Observatory" };

// Intro paints immediately; live integration state streams in behind it.
export default function IntegrationsPage() {
  return (
    <>
      <section className="lead route-note">
        <p className="lib-intro">
          Sources bring observations in. Destinations receive data only when a route and policy
          allow it.
        </p>
      </section>
      <Suspense fallback={<GridSkeleton count={4} />}>
        <IntegrationsSection />
      </Suspense>
    </>
  );
}
