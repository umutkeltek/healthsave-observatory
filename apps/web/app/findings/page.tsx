import type { Metadata } from "next";

import { EvidenceCard } from "../components/EvidenceCard";
import { WeeklyBriefCard } from "../components/WeeklyBriefCard";
import { safeFindings, safeLatest } from "../lib/load";

export const metadata: Metadata = { title: "Findings · HealthSave" };
export const dynamic = "force-dynamic";

export default async function FindingsPage() {
  const [latest, findings] = await Promise.all([safeLatest(), safeFindings()]);
  return (
    <>
      <section className="lead">
        <WeeklyBriefCard latest={latest} />
      </section>
      <section className="lead">
        <EvidenceCard findings={findings} />
      </section>
    </>
  );
}
