// Findings page sections - the weekly brief and the evidence list stream
// independently (both reads are cache()-deduped with the layout chrome).

import Link from "next/link";
import { EvidenceCard } from "../EvidenceCard";
import { FindingCard, PROOF_RANGE } from "../FindingCard";
import { WeeklyBriefCard } from "../WeeklyBriefCard";
import { cardMetricIsPlottable } from "../../lib/findingPresentation";
import { safeFindings, safeLatest, safeSeries, safeSeriesMany } from "../../lib/load";

export async function BriefSection() {
  const latest = await safeLatest();
  // Link "evidence" to the finding cards below (same page anchor).
  return (
    <section className="lead">
      <WeeklyBriefCard latest={latest} evidenceHref="#evidence" />
    </section>
  );
}

export async function FindingsEvidenceSection({
  selectedId,
}: { selectedId?: string } = {}) {
  const findings = await safeFindings();

  if (findings === null) {
    return (
      <section className="lead">
        <EvidenceCard findings={null} />
      </section>
    );
  }

  if (selectedId) {
    const selected = /^\d+$/.test(selectedId)
      ? findings.find((finding) => String(finding.id) === selectedId)
      : undefined;
    const metric = selected?.card?.metric;
    const series =
      metric && cardMetricIsPlottable(metric)
        ? await safeSeries(metric, PROOF_RANGE)
        : null;
    return (
      <section className="lead selected-finding" id="selected-finding">
        <div className="today-section-heading">
          <h2>Selected finding</h2>
          <Link href="/findings">
            All findings <span aria-hidden>→</span>
          </Link>
        </div>
        {selected ? (
          selected.card ? (
            <FindingCard finding={selected} series={series} />
          ) : (
            <EvidenceCard
              findings={[selected]}
              title="Finding evidence"
              subtitle="The recorded finding and its calculation."
            />
          )
        ) : (
          <article className="card">
            <h3>This finding is no longer in the current list</h3>
            <p>Open all findings to see the latest evidence.</p>
          </article>
        )}
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

  // One /api/v2/series batch for every DISTINCT plottable proof metric, resolved
  // ONCE here — instead of each FindingCard firing its own uncached safeSeries
  // (an N+1 storm, and worse when a metric repeats across cards; the findings
  // API returns up to 200). safeSeriesMany is cache()-deduped and NUL-keyed.
  const proofMetrics = [
    ...new Set(
      carded
        .map((finding) => finding.card?.metric ?? "")
        .filter((metric) => cardMetricIsPlottable(metric)),
    ),
  ];
  const seriesByMetric = await safeSeriesMany(proofMetrics, PROOF_RANGE);

  return (
    <section className="lead" id="evidence">
      <header className="findings-head">
        <h2>Evidence</h2>
        <p className="findings-sub">
          Each finding, computed from your own data — the claim, its proof
          against your baseline, and the numbers behind it.
        </p>
      </header>
      <div className="finding-cards">
        {carded.map((finding) => (
          <FindingCard
            key={finding.id}
            finding={finding}
            series={
              (finding.card && seriesByMetric.get(finding.card.metric)) || null
            }
          />
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
