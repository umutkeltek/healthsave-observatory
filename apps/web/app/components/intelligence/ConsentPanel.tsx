"use client";

import type { IntelligenceView } from "../../lib/api";
import type { IntelligenceForm } from "./useIntelligenceForm";

// Cloud egress consent — deliberately separate from saving a provider:
// entering a key is configuration, this card is the explicit opt-in.
export function ConsentPanel({ form, view }: { form: IntelligenceForm; view: IntelligenceView }) {
  const granted = view.consent.granted;
  return (
    <section className="intel-card intel-consent">
      <h3 className="intel-h">Cloud egress consent</h3>
      {granted ? (
        <>
          <div className="consent-state ok">
            ✓ Granted{view.consent.at ? ` on ${view.consent.at.slice(0, 10)}` : ""}. Redacted
            findings may be sent to your cloud provider.
          </div>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={form.pending}
            onClick={() => form.toggleConsent(false)}
          >
            Revoke consent
          </button>
        </>
      ) : (
        <>
          <p className="intel-sub">
            Entering a key isn’t consent. Cloud mode is configured but{" "}
            <strong>nothing is sent</strong> until you explicitly opt in here.
          </p>
          <label className="field field-check">
            <input
              type="checkbox"
              checked={form.consentChecked}
              onChange={(e) => form.setConsentChecked(e.target.checked)}
            />
            <span>
              I understand that redacted, derived findings will be sent to my chosen cloud
              provider. Raw health records never leave.
            </span>
          </label>
          <button
            type="button"
            className="btn"
            disabled={form.pending || !form.consentChecked}
            onClick={() => form.toggleConsent(true)}
          >
            Grant consent
          </button>
        </>
      )}
    </section>
  );
}
