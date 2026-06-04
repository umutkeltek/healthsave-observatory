// Privacy made tangible: the egress posture rendered as a chain of custody —
// source → store → engine → local model → (blocked) cloud — instead of a prose
// "we respect your privacy" card. Each step is a link in a visible chain.

export type VaultStep = { label: string; meta: string; blocked?: boolean };

export function LocalVaultReceipt({
  steps,
  seal = "No cloud egress",
}: {
  steps: VaultStep[];
  seal?: string;
}) {
  return (
    <article className="card vault">
      <div className="vault-head">
        <div className="card-title">Local Vault</div>
        <span className="vault-seal">{seal}</span>
      </div>
      <ul className="chain">
        {steps.map((step) => (
          <li key={step.label} className={`chain-step ${step.blocked ? "blocked" : ""}`}>
            <span className="chain-label">{step.label}</span>
            <span className="chain-meta">{step.meta}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}
