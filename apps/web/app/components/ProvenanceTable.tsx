import { reliabilityFor } from "../lib/healthOpinion";
import type { ProvenanceRow } from "../lib/provenance";

// Active streams as a chain-of-origin table: Source → Hardware → Stream id →
// Last sync → Freshness. The page owns the unreachable/demo decision and always
// passes populated rows there; an empty array here is a reachable backend with
// no source connected yet, which gets its own honest state.
export function ProvenanceTable({ rows, demo }: { rows: ProvenanceRow[]; demo?: boolean }) {
  if (rows.length === 0) {
    return (
      <article className="card">
        <div className="prov-head">
          <h2>Active Streams</h2>
        </div>
        <p className="empty">
          No streams yet — connect a source and each device appears here with its origin and freshness.
        </p>
      </article>
    );
  }

  return (
    <article className="card">
      <div className="prov-head">
        <h2>Active Streams</h2>
        <span className="chip mono">
          {rows.length} connection{rows.length === 1 ? "" : "s"}
        </span>
      </div>
      <div className="prov-scroll">
        <table className="prov">
          <thead>
            <tr>
              <th scope="col">Source / Origin</th>
              <th scope="col">Hardware</th>
              <th scope="col">Stream ID</th>
              <th scope="col">Last Sync</th>
              <th scope="col">Freshness</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.streamId}>
                <td className="prov-src">
                  <span className="prov-name" title={reliabilityFor(row.sourceName).note}>
                    {row.sourceName}
                  </span>
                  <span className="prov-origin">{row.origin}</span>
                </td>
                <td className="prov-hw">{row.hardware}</td>
                <td>
                  <code className="prov-id" title={row.streamId}>
                    {row.shortId}
                  </code>
                </td>
                <td className={`prov-sync ${row.stale ? "stale" : ""}`}>{row.lastSync}</td>
                <td>
                  <span
                    className="prov-bar"
                    role="img"
                    aria-label={`freshness ${Math.round(row.freshness * 100)} percent`}
                  >
                    <span
                      className={`prov-bar-fill ${row.stale ? "warn" : ""}`}
                      style={{ width: `${Math.round(row.freshness * 100)}%` }}
                    />
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {demo && (
        <p className="prov-demo-note">Showing demo provenance — connect a source to see your own streams.</p>
      )}
    </article>
  );
}
