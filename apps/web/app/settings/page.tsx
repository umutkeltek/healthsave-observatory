import type { Metadata } from "next";
import { Suspense } from "react";

import {
  AnalyticalTimeSection,
  PreferencesSection,
  ServicesSection,
  SystemSection,
} from "../components/sections/SettingsSections";
import { CardSkeleton, LeadSkeleton, RowSkeleton } from "../components/Skeletons";

export const revalidate = 30;
export const metadata: Metadata = { title: "Settings · HealthSave Observatory" };

// One place to see and manage everything configurable, end to end. Each
// section either manages inline (view mode, pins) or links to its dedicated
// surface (Intelligence, Integrations) - no orphaned settings. Sections
// stream independently so a slow backend never delays the cookie-backed prefs.
export default function SettingsPage() {
  return (
    <>
      <Suspense
        fallback={
          <>
            <LeadSkeleton />
            <LeadSkeleton />
          </>
        }
      >
        <PreferencesSection />
      </Suspense>
      <Suspense fallback={<CardSkeleton />}>
        <AnalyticalTimeSection />
      </Suspense>
      <Suspense fallback={<RowSkeleton />}>
        <ServicesSection />
      </Suspense>
      <Suspense fallback={<CardSkeleton />}>
        <SystemSection />
      </Suspense>
    </>
  );
}
