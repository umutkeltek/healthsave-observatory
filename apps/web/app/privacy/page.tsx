import type { Metadata } from "next";
import { Suspense } from "react";

import { PrivacySection } from "../components/sections/PrivacySections";
import { CardSkeleton } from "../components/Skeletons";

export const metadata: Metadata = { title: "Privacy · HealthSave" };
export const revalidate = 30;

export default function PrivacyPage() {
  return (
    <section className="lead">
      <Suspense fallback={<CardSkeleton />}>
        <PrivacySection />
      </Suspense>
    </section>
  );
}
