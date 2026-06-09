import type { Finding } from "../lib/api";

const TYPE_LABELS: Record<string, string> = {
  anomaly: "Anomaly",
  trend: "Trend",
  correlation: "Correlation",
  summary: "Summary",
  recovery_score: "Recovery",
};

// structured_data is untyped JSON — narrow before use so nothing unknown lands
// in a template literal (and so a malformed payload degrades gracefully).
function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function num(value: unknown, digits = 2): string | null {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : null;
}

// One-line human summary derived purely from the structured finding — no LLM
// involved (Tier-1: the evidence reads even when narration is off).
function summarize(finding: Finding): string {
  const d = finding.structured_data ?? {};
  switch (finding.finding_type) {
    case "anomaly": {
      const z = num(d.magnitude);
      const dir = str(d.direction) === "down" ? "below" : "above";
      return `${dir} baseline${z ? ` · z=${z}` : ""}`;
    }
    case "trend": {
      const p = num(d.p_value, 3);
      return `${str(d.direction) ?? "?"} trend over ${num(d.period_days, 0) ?? "?"}d${p ? ` · p=${p}` : ""}`;
    }
    case "correlation": {
      const r = num(d.coefficient);
      return `${str(d.metric_a) ?? "?"} ~ ${str(d.metric_b) ?? "?"}${r ? ` · r=${r}` : ""}`;
    }
    case "summary": {
      const avg = num(d.avg, 1);
      const delta = num(d.delta_pct_vs_baseline, 1);
      const sign = delta && Number(delta) >= 0 ? "+" : "";
      return `avg ${avg ?? "?"}${delta ? ` · ${sign}${delta}% vs baseline` : ""}`;
    }
    case "recovery_score": {
      const score = num(d.score, 0);
      return score ? `score ${score}/100` : "recovery score";
    }
    default:
      return finding.metric ?? "finding";
  }
}

// Why this finding earned a spot in the feed — the gate that surfaced it,
// derived from the structured data (no LLM). Makes the cut transparent.
function why(finding: Finding): string {
  const d = finding.structured_data ?? {};
  switch (finding.finding_type) {
    case "anomaly":
      return `${finding.severity ?? "flagged"} severity · deviated from your baseline`;
    case "trend": {
      const p = num(d.p_value, 3);
      return p ? `statistically significant trend (p=${p})` : "a sustained multi-day direction";
    }
    case "correlation": {
      const p = num(d.p_value, 3);
      return p
        ? `strong and significant enough to act on (p=${p})`
        : "a strong cross-metric association";
    }
    case "summary":
      return "period rollup vs your 30-day baseline";
    default:
      return "surfaced by the analysis engine";
  }
}

function EvidenceRow({ finding }: { finding: Finding }) {
  const kind = finding.finding_type ?? "finding";
  const label = TYPE_LABELS[kind] ?? kind;
  const entries = Object.entries(finding.structured_data ?? {});
  return (
    <li className="evidence-item">
      <div className="evidence-head">
        <span className="type-badge">{label}</span>
        <span className="evidence-metric">{finding.metric ?? "—"}</span>
        <span className="evidence-sum">{summarize(finding)}</span>
      </div>
      <div className="why">Why included: {why(finding)}</div>
      {entries.length > 0 && (
        <details className="calc">
          <summary>show calculation</summary>
          <dl className="calc-grid">
            {entries.map(([key, value]) => (
              <div className="calc-row" key={key}>
                <dt>{key}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </li>
  );
}

export function EvidenceCard({ findings }: { findings: Finding[] | null }) {
  if (findings === null) {
    return (
      <article className="card evidence">
        <h2>Evidence</h2>
        <p className="empty">Backend unreachable — start HealthSave Observatory and sync from the app.</p>
      </article>
    );
  }

  if (findings.length === 0) {
    return (
      <article className="card evidence">
        <h2>Evidence</h2>
        <p className="empty">
          No findings yet — anomalies, trends and correlations appear here as the engine runs.
        </p>
      </article>
    );
  }

  return (
    <article className="card evidence">
      <h2>Evidence</h2>
      <ul className="evidence-list">
        {findings.map((finding) => (
          <EvidenceRow key={finding.id} finding={finding} />
        ))}
      </ul>
      <div className="meta">
        {findings.length} finding{findings.length === 1 ? "" : "s"} · computed, not guessed
      </div>
    </article>
  );
}
