import type { Metadata } from "next";
import { Suspense } from "react";

import { ProvenanceSection } from "../components/sections/SourcesSections";
import { CardSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Sources · HealthSave" };
export const revalidate = 30;

// Data Provenance - where each reading came from, and how fresh it is. The
// intro paints immediately; the identity reads stream in behind it.
export default function SourcesPage() {
  return (
    <>
      <div className="prov-intro">
        <h2>Data Provenance</h2>
        <p>
          Ingestion streams are mapped to their hardware origins. Imperfect or conflicting signals are
          retained as immutable records in the Local Vault. We do not synthesize artificial consensus.
        </p>
      </div>

      <Suspense
        fallback={
          <div className="today-grid prov-grid" aria-hidden>
            <div className="col-8 prov-main">
              <CardSkeleton />
            </div>
            <div className="col-4 prov-aside">
              <CardSkeleton />
            </div>
          </div>
        }
      >
        <ProvenanceSection />
      </Suspense>
    </>
  );
}
