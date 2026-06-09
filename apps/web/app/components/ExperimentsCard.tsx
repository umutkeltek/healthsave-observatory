import type {
  Candidate,
  Candidates,
  Experiment,
  ExperimentList,
  ExperimentResult,
} from "../lib/api";
import { ExperimentActions } from "./ExperimentActions";
import { StartExperimentButton } from "./StartExperimentButton";

function short(metricId: string | null): string {
  if (!metricId) return "—";
  return (metricId.split(".").pop() ?? metricId).replace(/_/g, " ");
}

function coeffLabel(candidate: Candidate): string | null {
  return typeof candidate.coefficient === "number" ? candidate.coefficient.toFixed(2) : null;
}

function num(value: number | null, digits = 2): string {
  return typeof value === "number" ? value.toFixed(digits) : "—";
}

function pairKey(lever: string | null, outcome: string | null): string {
  return [lever ?? "", outcome ?? ""].sort().join("~");
}

// How much weight the inference carries — kept honest (descriptive vs tested).
function inferenceLabel(inference: string | null): string {
  switch (inference) {
    case "randomization_test":
      return "randomization test";
    case "descriptive_only":
      return "descriptive only — too few blocks to test";
    case "observational":
      return "observational — association, not cause";
    case "insufficient":
      return "not enough data yet";
    default:
      return inference ?? "—";
  }
}

function adherenceStatus(result: ExperimentResult): string | null {
  const adherence = result.adherence;
  if (!adherence || typeof adherence !== "object") return null;
  const status = (adherence as { status?: unknown }).status;
  return typeof status === "string" ? status : null;
}

function adherenceNote(result: ExperimentResult): string | null {
  const adherence = result.adherence;
  if (!adherence || typeof adherence !== "object") return null;
  const note = (adherence as { note?: unknown }).note;
  return typeof note === "string" ? note : null;
}

function ResultBlock({ result }: { result: ExperimentResult }) {
  const observational = result.inference === "observational";
  const insufficient = result.inference === "insufficient";
  const adherence = adherenceStatus(result);
  return (
    <div className="exp-result">
      <div className="exp-result-head">
        <span className="type-badge">{observational ? "early read" : "result"}</span>
        {result.summary && <span className="evidence-sum">{result.summary}</span>}
      </div>
      {!insufficient && (
        <div className="exp-stats">
          {result.p_value != null ? (
            <span>p={num(result.p_value, 3)}</span>
          ) : (
            <span>{inferenceLabel(result.inference)}</span>
          )}
          {result.effect_size != null && <span>d={num(result.effect_size)}</span>}
          {result.n_a != null && result.n_b != null && (
            <span>
              {result.n_a} vs {result.n_b} days
            </span>
          )}
          {adherence && <span className={`adherence ${adherence}`}>adherence: {adherence}</span>}
        </div>
      )}
      {(result.caveat || adherenceNote(result)) && (
        <details className="calc">
          <summary>caveat &amp; calculation</summary>
          <div className="exp-caveat">
            {adherenceNote(result) && <p>{adherenceNote(result)}</p>}
            {result.caveat && <p>{result.caveat}</p>}
            <dl className="calc-grid">
              <div className="calc-row">
                <dt>baseline mean</dt>
                <dd>{num(result.mean_a)}</dd>
              </div>
              <div className="calc-row">
                <dt>intervention mean</dt>
                <dd>{num(result.mean_b)}</dd>
              </div>
              <div className="calc-row">
                <dt>difference</dt>
                <dd>{num(result.diff)}</dd>
              </div>
              <div className="calc-row">
                <dt>inference</dt>
                <dd>{inferenceLabel(result.inference)}</dd>
              </div>
            </dl>
          </div>
        </details>
      )}
    </div>
  );
}

function ExperimentRow({ experiment }: { experiment: Experiment }) {
  const prog = experiment.progress;
  const retro = experiment.results.retrospective;
  const controlled = experiment.results.controlled;
  const collecting = experiment.status === "collecting";
  return (
    <li className={`exp-item ${experiment.status === "abandoned" ? "muted-item" : ""}`}>
      <div className="cand-head">
        <span className="cand-hyp">
          {experiment.lever} → {experiment.outcome}
        </span>
        <span className={`badge ${experiment.status === "completed" ? "ready" : "waiting"}`}>
          {experiment.status}
        </span>
      </div>
      {experiment.hypothesis && <p className="cand-rationale">&ldquo;{experiment.hypothesis}&rdquo;</p>}

      {collecting && (
        <div className="exp-progress">
          <div className="exp-bar">
            <div className="exp-bar-fill" style={{ width: `${Math.round(prog.pct * 100)}%` }} />
          </div>
          <div className="meta">
            {prog.is_complete
              ? "window complete — analyze now"
              : `day ${prog.day_index}/${prog.total_days}${
                  prog.current_phase ? ` · phase ${prog.current_phase}` : ""
                } · ${prog.days_remaining} days left`}
          </div>
        </div>
      )}

      {retro && <ResultBlock result={retro} />}
      {controlled && <ResultBlock result={controlled} />}

      <ExperimentActions id={experiment.id} status={experiment.status} />
    </li>
  );
}

function TestableRow({ candidate }: { candidate: Candidate }) {
  const r = coeffLabel(candidate);
  const lever = candidate.readiness.lever;
  const outcome = candidate.readiness.outcome;
  return (
    <li className="cand-item">
      <div className="cand-head">
        <span className="cand-hyp">
          {short(lever)} → {short(outcome)}
        </span>
        <span className="badge ready">testable</span>
        {r && <span className="cand-strength">r={r}</span>}
      </div>
      {candidate.readiness.suggested_protocol && (
        <p className="cand-protocol">{candidate.readiness.suggested_protocol}</p>
      )}
      {lever && outcome && <StartExperimentButton lever={lever} outcome={outcome} />}
    </li>
  );
}

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

export function ExperimentsCard({
  experiments,
  candidates,
}: {
  experiments: ExperimentList | null;
  candidates: Candidates | null;
}) {
  if (experiments === null && candidates === null) {
    return (
      <article className="card experiments">
        <h2>What to Try Next</h2>
        <p className="empty">Backend unreachable — start HealthSave Observatory and sync from the app.</p>
      </article>
    );
  }

  const exps = experiments?.experiments ?? [];
  const allCandidates = candidates?.candidates ?? [];
  const testable = allCandidates.filter((c) => c.readiness.verdict === "testable");
  const notTestable = allCandidates.filter((c) => c.readiness.verdict !== "testable");

  // Don't offer to start a pair that's already running.
  const runningPairs = new Set(
    exps
      .filter((e) => e.status !== "abandoned")
      .map((e) => pairKey(e.lever_metric_id, e.outcome_metric_id)),
  );
  const startable = testable.filter(
    (c) => !runningPairs.has(pairKey(c.readiness.lever, c.readiness.outcome)),
  );

  return (
    <article className="card experiments">
      <h2>What to Try Next</h2>

      {exps.length > 0 && (
        <>
          <div className="brief-meta">Your experiments</div>
          <ul className="cand-list">
            {exps.map((experiment) => (
              <ExperimentRow key={experiment.id} experiment={experiment} />
            ))}
          </ul>
        </>
      )}

      <div className="brief-meta">
        {startable.length > 0
          ? `${startable.length} ${startable.length === 1 ? "idea" : "ideas"} to start`
          : "Start something new"}
      </div>
      {startable.length > 0 ? (
        <ul className="cand-list">
          {startable.map((candidate) => (
            <TestableRow key={pairKey(candidate.metric_a, candidate.metric_b)} candidate={candidate} />
          ))}
        </ul>
      ) : (
        <p className="empty">
          {exps.length > 0
            ? "Nothing new to start right now — the strongest fresh correlations link metrics you can't set by choice."
            : "No candidates yet — correlations become experiment ideas once the engine finds them."}
        </p>
      )}

      {notTestable.length > 0 && (
        <details className="calc">
          <summary>{notTestable.length} not directly testable</summary>
          <ul className="cand-list">
            {notTestable.map((candidate) => (
              <NotTestableRow
                key={pairKey(candidate.metric_a, candidate.metric_b)}
                candidate={candidate}
              />
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
