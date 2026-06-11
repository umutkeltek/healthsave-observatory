"use client";

import { useState, useTransition } from "react";

import { triggerAnalysisAction } from "../lib/actions";

// "Compute relationships now" affordance on /relationships. Mirrors
// RefreshInsightsButton's calm pending caption; a disabled analysis block
// (409) gets a quiet pointer to /intelligence instead of an error tone.
export function RunCorrelationButton() {
  const [pending, startTransition] = useTransition();
  const [note, setNote] = useState<string | null>(null);

  const run = () =>
    startTransition(async () => {
      setNote(null);
      const result = await triggerAnalysisAction("correlation_analysis");
      if (!result.ok) {
        const detail = result.error ?? "";
        setNote(
          detail.includes("disabled")
            ? "Analysis is off — enable it under Intelligence."
            : detail || "Could not run the analysis.",
        );
      }
    });

  return (
    <span className="brief-refresh">
      {pending && (
        <span className="brief-narrating mono" aria-live="polite">
          <span className="live-dot" aria-hidden />
          computing…
        </span>
      )}
      {!pending && note && (
        <span className="brief-note mono">
          {note.includes("Intelligence") ? (
            <>
              Analysis is off — <a href="/intelligence">enable it</a>.
            </>
          ) : (
            note
          )}
        </span>
      )}
      <button type="button" className="btn btn-ghost" disabled={pending} onClick={run}>
        Compute now
      </button>
    </span>
  );
}
