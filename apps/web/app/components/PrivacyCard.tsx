import { isNarratorOff, type EgressClass, type Privacy } from "../lib/api";

const CLASS_LABELS: Record<string, string> = {
  raw_observations: "Raw observations",
  findings: "Derived findings",
  aggregates: "Aggregates",
  evidence: "Evidence snippets",
  prompt: "Narrator prompt",
};

const CLASS_COPY: Record<string, string> = {
  raw_observations: "Reading-level health records.",
  findings: "Statistical conclusions already computed on this host.",
  aggregates: "Rollups and summaries, not individual readings.",
  evidence: "Small proof lines attached to findings.",
  prompt: "The redacted package assembled for narration.",
};

const ORDER = ["raw_observations", "findings", "aggregates", "evidence", "prompt"];

function label(payloadClass: string): string {
  return CLASS_LABELS[payloadClass] ?? payloadClass.replace(/_/g, " ");
}

function description(payloadClass: string): string {
  return CLASS_COPY[payloadClass] ?? "Classified by the Observatory egress policy.";
}

function normalizeRows(privacy: Privacy): EgressClass[] {
  const byClass = new Map<string, EgressClass>();
  for (const row of privacy.egress) byClass.set(row.payload_class, row);

  byClass.set("raw_observations", {
    payload_class: "raw_observations",
    allowed: false,
    leaves_host: Boolean(privacy.raw_observations_leave_host),
    reason: "Raw observations are categorically blocked from cloud egress.",
  });

  return [
    ...ORDER.filter((key) => byClass.has(key)).map((key) => byClass.get(key)!),
    ...[...byClass.values()].filter((row) => !ORDER.includes(row.payload_class)),
  ];
}

function rowStatus(row: EgressClass, privacy: Privacy): { label: string; tone: string } {
  if (row.leaves_host) return { label: `Leaves to ${privacy.provider}`, tone: "leaves" };
  if (row.allowed && privacy.is_local) return { label: "Allowed locally", tone: "onhost" };
  if (row.allowed) return { label: "Eligible, blocked now", tone: "blocked" };
  return { label: "Blocked", tone: "blocked" };
}

function policyReason(row: EgressClass, privacy: Privacy): string {
  if (row.payload_class === "raw_observations") {
    return "Raw readings are never eligible for cloud narration.";
  }
  if (row.leaves_host && row.payload_class === "prompt") {
    return privacy.cloud_prompt_redaction === false
      ? "Built from derived findings after consent. Prompt redaction is off."
      : "Built from redacted derived findings after consent.";
  }
  if (row.leaves_host) {
    return "Allowed because cloud narration is active and consented.";
  }
  if (row.allowed && privacy.is_local) {
    return "Allowed only inside the local route.";
  }
  if (row.allowed) {
    return "Eligible by class, but no bytes leave while cloud egress is off.";
  }
  return "Denied by the default-deny egress policy.";
}

function postureTitle(privacy: Privacy): string {
  if (isNarratorOff(privacy.provider)) return "On-host only";
  if (privacy.is_local) return "Local narration";
  if (privacy.cloud_active) return "Cloud narration active";
  return "Cloud provider configured, egress off";
}

export function PrivacyCard({ privacy }: { privacy: Privacy | null }) {
  if (privacy === null) {
    return (
      <article className="card privacy">
        <h2>What Leaves This Host</h2>
        <p className="empty">Backend unreachable. Start HealthSave Observatory to see egress posture.</p>
      </article>
    );
  }

  const narratorOff = isNarratorOff(privacy.provider);
  const local = narratorOff || privacy.is_local || !privacy.cloud_active;
  const rows = normalizeRows(privacy);
  const leaving = rows.filter((row) => row.leaves_host).map((row) => label(row.payload_class));
  const redaction = privacy.cloud_prompt_redaction ?? true;
  const detail = narratorOff
    ? "No narrator is configured. Findings are computed locally and no prompt is assembled."
    : privacy.is_local
      ? `Narration runs locally through ${privacy.provider}. No health data leaves this host.`
      : privacy.cloud_active
        ? `Only policy-approved, derived classes leave for ${privacy.provider}. Raw observations remain blocked.`
        : `${privacy.provider} is configured, but cloud egress is off. Nothing currently leaves this host.`;

  return (
    <article className="card privacy">
      <div className="card-head split">
        <div>
          <h2>What Leaves This Host</h2>
          <p className="card-subtitle">{detail}</p>
        </div>
        <span className={`badge ${local ? "ready" : "waiting"}`}>
          {postureTitle(privacy)}
        </span>
      </div>

      <div className="privacy-kpis">
        <div>
          <span>Raw observations</span>
          <strong>Blocked</strong>
        </div>
        <div>
          <span>Current destination</span>
          <strong>{narratorOff ? "none" : privacy.provider}</strong>
        </div>
        <div>
          <span>Cloud egress</span>
          <strong>{privacy.cloud_active ? "active" : "off"}</strong>
        </div>
        <div>
          <span>Prompt redaction</span>
          <strong>{redaction ? "on" : "off"}</strong>
        </div>
      </div>

      <div className="policy-list" aria-label="Egress policy by payload class">
        {rows.map((row) => {
          const status = rowStatus(row, privacy);
          return (
            <div className="policy-row" key={row.payload_class}>
              <div>
                <strong>{label(row.payload_class)}</strong>
                <span>{description(row.payload_class)}</span>
              </div>
              <span className={`policy-status ${status.tone}`}>{status.label}</span>
              <p>{policyReason(row, privacy)}</p>
            </div>
          );
        })}
      </div>

      <div className="chips privacy-leaving" aria-label="Classes leaving host now">
        {leaving.length > 0 ? (
          leaving.map((name) => <span className="chip" key={name}>{name}</span>)
        ) : (
          <span className="chip">No classes leave this host now</span>
        )}
      </div>

      <div className="assurance">Raw observations never leave host.</div>
    </article>
  );
}
