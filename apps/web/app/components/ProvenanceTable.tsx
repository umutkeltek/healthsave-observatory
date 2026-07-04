import { reliabilityFor } from "../lib/healthOpinion";
import type { ProvenanceRow } from "../lib/provenance";

function freshnessLabel(row: ProvenanceRow): string {
  if (row.stale) return "Needs attention";
  if (row.freshness >= 0.9) return "Fresh";
  if (row.freshness >= 0.65) return "Recent";
  return "Aging";
}

export function ProvenanceTable({ rows, demo }: { rows: ProvenanceRow[]; demo?: boolean }) {
  if (rows.length === 0) {
    return (
      <article className="card prov-card-shell">
        <div className="prov-head">
          <h2>Active Streams</h2>
        </div>
        <p className="empty">No streams yet. Connect a source to see devices, sync age, and origin.</p>
      </article>
    );
  }

  return (
    <article className="card prov-card-shell">
      <div className="prov-head">
        <div>
          <h2>Active Streams</h2>
          <p className="card-subtitle">Human source names first. Raw stream tokens stay available in details.</p>
        </div>
        <span className="chip mono">
          {rows.length} connection{rows.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="prov-card-list">
        {rows.map((row, index) => {
          const pct = Math.round(row.freshness * 100);
          const reliability = reliabilityFor(row.sourceName);

          return (
            <section key={row.streamId} className={`prov-source-card ${row.stale ? "is-stale" : ""}`}>
              <div className="prov-source-main">
                <span className="prov-source-index">Connection {index + 1}</span>
                <h3 title={reliability.note}>{row.sourceName}</h3>
                <p>
                  {row.hardware} via {row.origin}
                </p>
              </div>

              <div className="prov-source-sync">
                <span>Last sync</span>
                <strong className={row.stale ? "stale" : ""}>{row.lastSync}</strong>
                <em>{freshnessLabel(row)}</em>
              </div>

              <div className="prov-source-meter" aria-label={`freshness ${pct} percent`}>
                <span style={{ width: `${pct}%` }} />
              </div>

              <details className="prov-technical">
                <summary>Stream details</summary>
                <dl>
                  <div>
                    <dt>Stream token</dt>
                    <dd>
                      <code>{row.shortId}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Full ID</dt>
                    <dd>
                      <code>{row.streamId}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Reliability</dt>
                    <dd>{reliability.note}</dd>
                  </div>
                </dl>
              </details>
            </section>
          );
        })}
      </div>

      {demo && <p className="prov-demo-note">Showing demo provenance. Connect a source to see your own streams.</p>}
    </article>
  );
}
