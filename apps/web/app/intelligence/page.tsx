import type { Metadata } from "next";

import { IntelligenceSettings } from "../components/IntelligenceSettings";
import { PrivacyCard } from "../components/PrivacyCard";
import { safeIntelligence, safePrivacy } from "../lib/load";

export const metadata: Metadata = { title: "Intelligence · HealthSave" };
export const dynamic = "force-dynamic";

export default async function IntelligencePage() {
  const [intelligence, privacy] = await Promise.all([safeIntelligence(), safePrivacy()]);
  return (
    <section className="lead">
      <header className="intel-head">
        <h1 className="intel-title">Intelligence</h1>
        <p className="intel-tag">
          Choose how your briefs are written — and exactly what, if anything, leaves your host.
        </p>
      </header>
      <IntelligenceSettings initial={intelligence} />
      <PrivacyCard privacy={privacy} />
    </section>
  );
}
