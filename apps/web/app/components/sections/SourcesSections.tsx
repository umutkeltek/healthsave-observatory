// Sources page section - provenance table, divergence log, and coverage share
// the same identity reads, so they stream behind one boundary. An UNREACHABLE
// backend says so: demo provenance never stands in for the person's own
// sources outside /demo.

import { CoverageCard } from "../CoverageCard";
import { DivergenceLog } from "../DivergenceLog";
import { ProvenanceTable } from "../ProvenanceTable";
import { buildCoverage, buildProvenanceRows } from "../../lib/provenance";
import { safeSources, safeStreams } from "../../lib/load";

function VaultNote() {
  return (
    <article className="card vault-note">
      <h2>Local Vault</h2>
      <p className="empty">
        Raw telemetry is stored on this host. Egress to external analysis requires explicit opt-in and
        passes automated redaction first.
      </p>
    </article>
  );
}

export async function ProvenanceSection() {
  const [streams, sources] = await Promise.all([safeStreams(), safeSources()]);

  if (streams === null) {
    return (
      <>
        <div className="today-grid prov-grid">
          <div className="col-8 prov-main">
            <article className="card">
              <p className="empty">
                The Observatory API did not answer, so sources and their freshness cannot be shown right now.
              </p>
            </article>
          </div>
          <div className="col-4 prov-aside">
            <VaultNote />
          </div>
        </div>
        <footer className="foot">provenance unavailable · nothing left this host</footer>
      </>
    );
  }

  const rows = buildProvenanceRows(streams, sources ?? []);
  const coverage = buildCoverage(rows);

  return (
    <>
      <div className="today-grid prov-grid">
        <div className="col-8 prov-main">
          <ProvenanceTable rows={rows} />
          <div className="section-label">Divergence Logs</div>
          <DivergenceLog divergences={[]} live />
        </div>

        <div className="col-4 prov-aside">
          <CoverageCard {...coverage} />
          <VaultNote />
        </div>
      </div>

      <footer className="foot">
        {`${coverage.total} stream${coverage.total === 1 ? "" : "s"} · provenance from the v2 identity registry · nothing left this host`}
      </footer>
    </>
  );
}
