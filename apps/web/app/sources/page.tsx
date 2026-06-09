import type { Metadata } from "next";

import { CoverageCard } from "../components/CoverageCard";
import { DivergenceLog } from "../components/DivergenceLog";
import { ProvenanceTable } from "../components/ProvenanceTable";
import {
  buildCoverage,
  buildProvenanceRows,
  DEMO_COVERAGE,
  DEMO_DIVERGENCES,
  DEMO_PROVENANCE,
} from "../lib/provenance";
import { safeSources, safeStreams } from "../lib/load";

export const metadata: Metadata = { title: "Sources · HealthSave" };
export const dynamic = "force-dynamic";

// Data Provenance — where each reading came from, and how fresh it is. The
// streams table is wired to the v2 identity registry. Only an UNREACHABLE
// backend (a fresh clone with nothing running) falls back to a clearly labelled
// demo so the surface is alive for a screenshot; a reachable backend with no
// source connected yet shows its own honest "no streams" state rather than demo.
export default async function SourcesPage() {
  const [streams, sources] = await Promise.all([safeStreams(), safeSources()]);

  const isDemo = streams === null;
  const rows = isDemo ? DEMO_PROVENANCE : buildProvenanceRows(streams, sources ?? []);
  const coverage = isDemo ? DEMO_COVERAGE : buildCoverage(rows);
  const live = !isDemo;

  return (
    <>
      <div className="prov-intro">
        <h2>Data Provenance</h2>
        <p>
          Ingestion streams are mapped to their hardware origins. Imperfect or conflicting signals are
          retained as immutable records in the Local Vault. We do not synthesize artificial consensus.
        </p>
      </div>

      <div className="today-grid prov-grid">
        <div className="col-8 prov-main">
          <ProvenanceTable rows={rows} demo={isDemo} />
          <div className="section-label">Divergence Logs</div>
          <DivergenceLog divergences={DEMO_DIVERGENCES} live={live} />
        </div>

        <div className="col-4 prov-aside">
          <CoverageCard {...coverage} />
          <article className="card vault-note">
            <h2>Local Vault</h2>
            <p className="empty">
              Raw telemetry is stored on this host. Egress to external analysis requires explicit opt-in and
              passes automated redaction first.
            </p>
          </article>
        </div>
      </div>

      <footer className="foot">
        {live
          ? `${coverage.total} stream${coverage.total === 1 ? "" : "s"} · provenance from the v2 identity registry · nothing left this host`
          : "demo data · illustrative provenance · nothing left this host"}
      </footer>
    </>
  );
}
