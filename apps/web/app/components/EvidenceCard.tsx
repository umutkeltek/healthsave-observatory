import type { Finding } from "../lib/api";
import {
  displayItemsForFindings,
  findingProofLine,
  groupFindingsForDisplay,
  type FindingDisplayItem,
  userFindingSummary,
  userFindingTitle,
} from "../lib/findingPresentation";

const TYPE_LABELS: Record<string, string> = {
  anomaly: "Attention",
  trend: "Trend",
  correlation: "Relationship",
  summary: "Summary",
  recovery_score: "Recovery",
};

function EvidenceRow({ finding }: { finding: Finding }) {
  const kind = finding.finding_type ?? "finding";
  const label = TYPE_LABELS[kind] ?? kind;
  const entries = Object.entries(finding.structured_data ?? {});

  return (
    <li className="evidence-item insight-item">
      <div className="evidence-head insight-head">
        <span className="type-badge">{label}</span>
        <span className="evidence-metric">{userFindingTitle(finding)}</span>
      </div>
      <p className="evidence-sum insight-summary">{userFindingSummary(finding)}</p>
      <div className="why">Why included: {findingProofLine(finding)}</div>

      {entries.length > 0 && (
        <details className="calc">
          <summary>Show calculation</summary>
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

function EvidenceCluster({ item }: { item: Extract<FindingDisplayItem, { kind: "cluster" }> }) {
  return (
    <li className="evidence-item insight-item evidence-cluster">
      <div className="evidence-head insight-head">
        <span className="type-badge">Summary</span>
        <span className="evidence-metric">{item.title}</span>
        <span className="count-pill">{item.count}</span>
      </div>
      <p className="evidence-sum insight-summary">{item.summary}</p>
      <div className="why">Why included: {item.proof}</div>
      <details className="calc">
        <summary>Show individual checks</summary>
        <ol className="cluster-list">
          {item.findings.map((finding) => (
            <li key={finding.id}>
              <span>{userFindingSummary(finding)}</span>
              {finding.created_at && <span>{new Date(finding.created_at).toLocaleDateString()}</span>}
            </li>
          ))}
        </ol>
      </details>
    </li>
  );
}

function EvidenceItem({ item }: { item: FindingDisplayItem }) {
  if (item.kind === "cluster") return <EvidenceCluster item={item} />;
  return <EvidenceRow finding={item.finding} />;
}

export function EvidenceCard({
  findings,
  compact = false,
}: {
  findings: Finding[] | null;
  compact?: boolean;
}) {
  if (findings === null) {
    return (
      <article className="card evidence">
        <h2>Findings</h2>
        <p className="empty">Backend unreachable. Start HealthSave Observatory and sync the app.</p>
      </article>
    );
  }

  if (findings.length === 0) {
    return (
      <article className="card evidence">
        <h2>Findings</h2>
        <p className="empty">No findings yet. Trends, anomalies, and recovery context appear after baselines build.</p>
      </article>
    );
  }

  const groups = groupFindingsForDisplay(findings).filter((group) => group.findings.length > 0);
  const visibleGroups = compact ? groups.slice(0, 3) : groups;
  const maxPerGroup = compact ? 2 : 6;

  return (
    <article className="card evidence">
      <div className="card-head split">
        <div>
          <h2>What changed</h2>
          <p className="card-subtitle">Important signals first. Calculations stay available when you need proof.</p>
        </div>
        <span className="meta">
          {findings.length} finding{findings.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="finding-groups">
        {visibleGroups.map((group) => {
          const items = displayItemsForFindings(group.findings);
          const shown = items.slice(0, maxPerGroup);
          const shownCount = shown.reduce((total, item) => total + item.count, 0);
          const hidden = group.findings.length - shownCount;

          return (
            <section className={`finding-group finding-group-${group.id}`} key={group.id}>
              <div className="finding-group-head">
                <div>
                  <h3>{group.title}</h3>
                  <p>{group.description}</p>
                </div>
                <span className="count-pill">{group.findings.length}</span>
              </div>
              <ul className="evidence-list">
                {shown.map((item) => (
                  <EvidenceItem key={item.key} item={item} />
                ))}
              </ul>
              {hidden > 0 && <div className="meta">+ {hidden} more findings in this group</div>}
            </section>
          );
        })}
      </div>

      <div className="meta">Computed locally from your Observatory data.</div>
    </article>
  );
}
