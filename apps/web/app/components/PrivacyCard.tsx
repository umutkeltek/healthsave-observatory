import type { Privacy } from "../lib/api";

const CLASS_LABELS: Record<string, string> = {
  raw_observations: "raw observations",
  findings: "findings",
  aggregates: "aggregates",
  evidence: "evidence",
  prompt: "prompt",
};

function label(payloadClass: string): string {
  return CLASS_LABELS[payloadClass] ?? payloadClass;
}

export function PrivacyCard({ privacy }: { privacy: Privacy | null }) {
  if (privacy === null) {
    return (
      <article className="card privacy">
        <h2>What Leaves This Host</h2>
        <p className="empty">Backend unreachable — start HealthSave Observatory to see your egress posture.</p>
      </article>
    );
  }

  const local = !privacy.cloud_active;
  const detail = privacy.is_local
    ? `Insights are generated locally by ${privacy.provider}. No health data is sent anywhere.`
    : privacy.cloud_active
      ? `Derived insights are sent to ${privacy.provider}. Raw health records never leave.`
      : `${privacy.provider} is configured, but cloud egress is off — nothing leaves this host.`;

  const leaving = privacy.egress.filter((e) => e.leaves_host).map((e) => label(e.payload_class));

  return (
    <article className="card privacy">
      <h2>What Leaves This Host</h2>

      <div className="readiness-head">
        <span className="cand-hyp">{local ? "Local-only" : "Cloud narration on"}</span>
        <span className={`badge ${local ? "ready" : "waiting"}`}>
          {local ? "nothing leaves" : `→ ${privacy.provider}`}
        </span>
      </div>

      <p className="brief-body">{detail}</p>

      {privacy.cloud_active && leaving.length > 0 && (
        <div className="chips">
          {leaving.map((name) => (
            <span className="chip" key={name}>
              ↗ {name}
            </span>
          ))}
        </div>
      )}

      {/* The privacy invariant, always true regardless of opt-in. */}
      <div className="assurance">Raw observations never leave the host.</div>
    </article>
  );
}
