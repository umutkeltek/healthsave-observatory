// Sources page section - provenance table, divergence log, and coverage share
// the same identity reads, so they stream behind one boundary. Only an
// UNREACHABLE backend falls back to the clearly-labelled demo (see page).

import { CoverageCard } from "../CoverageCard";
import { DivergenceLog } from "../DivergenceLog";
import { ProvenanceTable } from "../ProvenanceTable";
import {
  buildCoverage,
  buildProvenanceRows,
  DEMO_COVERAGE,
  DEMO_DIVERGENCES,
  DEMO_PROVENANCE,
} from "../../lib/provenance";
import { safeSources, safeStreams } from "../../lib/load";

export async function ProvenanceSection() {
  const [streams, sources] = await Promise.all([safeStreams(), safeSources()]);

  const isDemo = streams === null;
  const rows = isDemo ? DEMO_PROVENANCE : buildProvenanceRows(streams, sources ?? []);
  const coverage = isDemo ? DEMO_COVERAGE : buildCoverage(rows);
  const live = !isDemo;

  return (
    <>
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
