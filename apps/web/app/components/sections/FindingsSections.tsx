// Findings page sections - the weekly brief and the evidence list stream
// independently (both reads are cache()-deduped with the layout chrome).

import { EvidenceCard } from "../EvidenceCard";
import { FindingCard } from "../FindingCard";
import { WeeklyBriefCard } from "../WeeklyBriefCard";
import { safeFindings, safeLatest } from "../../lib/load";

export async function BriefSection() {
  const latest = await safeLatest();
  // Link "evidence" to the finding cards below (same page anchor).
  return (
    <section className="lead">
      <WeeklyBriefCard latest={latest} evidenceHref="#evidence" />
    </section>
  );
}

export async function FindingsEvidenceSection() {
  const findings = await safeFindings();

  if (findings === null) {
    return (
      <section className="lead">
        <EvidenceCard findings={null} />
      </section>
    );
  }

  // Versioning story stays VISIBLE-honest: findings that carry a computed card
  // (schema_version 1) render as the ONE card grammar, newest first (the API
  // already orders newest-first); legacy findings (card=null, schema_version 0)
  // keep their prior rendering, framed as "Earlier findings".
  const carded = findings.filter((finding) => finding.card);
  const legacy = findings.filter((finding) => !finding.card);

  if (carded.length === 0) {
    return (
      <section className="lead" id="evidence">
        <EvidenceCard findings={legacy} />
      </section>
    );
  }

  return (
    <section className="lead" id="evidence">
      <div className="finding-cards">
        {carded.map((finding) => (
          <FindingCard key={finding.id} finding={finding} />
        ))}
      </div>
      {legacy.length > 0 && (
        <EvidenceCard
          findings={legacy}
          title="Earlier findings"
          subtitle="Recorded before evidence cards existed — kept exactly as computed (schema v0)."
        />
      )}
    </section>
  );
}
