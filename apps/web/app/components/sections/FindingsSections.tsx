// Findings page sections — the weekly brief and the evidence list stream
// independently (both reads are cache()-deduped with the layout chrome).

import { EvidenceCard } from "../EvidenceCard";
import { WeeklyBriefCard } from "../WeeklyBriefCard";
import { safeFindings, safeLatest } from "../../lib/load";

export async function BriefSection() {
  const latest = await safeLatest();
  return (
    <section className="lead">
      <WeeklyBriefCard latest={latest} />
    </section>
  );
}

export async function FindingsEvidenceSection() {
  const findings = await safeFindings();
  return (
    <section className="lead">
      <EvidenceCard findings={findings} />
    </section>
  );
}
