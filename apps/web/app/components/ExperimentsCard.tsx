import type { Candidate, Candidates } from "../lib/api";

function short(metricId: string | null): string {
  if (!metricId) return "—";
  return (metricId.split(".").pop() ?? metricId).replace(/_/g, " ");
}

function coeffLabel(candidate: Candidate): string | null {
  return typeof candidate.coefficient === "number" ? candidate.coefficient.toFixed(2) : null;
}

// A testable candidate is an action: lever → outcome, with a protocol to run.
function TestableRow({ candidate }: { candidate: Candidate }) {
  const r = coeffLabel(candidate);
  return (
    <li className="cand-item">
      <div className="cand-head">
        <span className="cand-hyp">
          {short(candidate.readiness.lever)} → {short(candidate.readiness.outcome)}
        </span>
        <span className="badge ready">testable</span>
        {r && <span className="cand-strength">r={r}</span>}
      </div>
      {candidate.readiness.suggested_protocol && (
        <p className="cand-protocol">{candidate.readiness.suggested_protocol}</p>
      )}
      {candidate.readiness.required_days != null && (
        <div className="meta">~{candidate.readiness.required_days} days to run</div>
      )}
    </li>
  );
}

// A non-testable candidate still informs — it says why it isn't an experiment.
function NotTestableRow({ candidate }: { candidate: Candidate }) {
  const r = coeffLabel(candidate);
  return (
    <li className="cand-item muted-item">
      <div className="cand-head">
        <span className="cand-hyp">
          {short(candidate.metric_a)} ~ {short(candidate.metric_b)}
        </span>
        <span className="badge waiting">not testable</span>
        {r && <span className="cand-strength">r={r}</span>}
      </div>
      <p className="cand-rationale">{candidate.readiness.rationale}</p>
    </li>
  );
}

export function ExperimentsCard({ candidates }: { candidates: Candidates | null }) {
  if (candidates === null) {
    return (
      <article className="card experiments">
        <h2>What to Try Next</h2>
        <p className="empty">Backend unreachable — start datahub and sync from HealthSave.</p>
      </article>
    );
  }

  if (candidates.candidates.length === 0) {
    return (
      <article className="card experiments">
        <h2>What to Try Next</h2>
        <p className="empty">
          No candidates yet — correlations become experiment ideas once the engine finds them.
        </p>
      </article>
    );
  }

  const testable = candidates.candidates.filter((c) => c.readiness.verdict === "testable");
  const notTestable = candidates.candidates.filter((c) => c.readiness.verdict !== "testable");

  return (
    <article className="card experiments">
      <h2>What to Try Next</h2>
      <div className="brief-meta">
        {candidates.testable_count} of {candidates.count} correlations are testable as experiments
      </div>

      {testable.length > 0 ? (
        <ul className="cand-list">
          {testable.map((candidate) => (
            <TestableRow key={`${candidate.metric_a}~${candidate.metric_b}`} candidate={candidate} />
          ))}
        </ul>
      ) : (
        <p className="empty">
          No directly testable candidates yet — the strongest correlations link metrics you can&apos;t
          set by choice.
        </p>
      )}

      {notTestable.length > 0 && (
        <details className="calc">
          <summary>{notTestable.length} not directly testable</summary>
          <ul className="cand-list">
            {notTestable.map((candidate) => (
              <NotTestableRow
                key={`${candidate.metric_a}~${candidate.metric_b}`}
                candidate={candidate}
              />
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
