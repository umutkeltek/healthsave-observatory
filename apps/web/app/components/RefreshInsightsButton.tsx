"use client";

import { useState, useTransition } from "react";

import { triggerAnalysisAction } from "../lib/actions";

// "Refresh the narration" affordance on the brief card. Pending state shows a
// calm mint "narrating" caption (the honest alternative to a fake typewriter —
// the backend generates whole briefs, it does not stream tokens). A disabled
// analysis block (409) gets a quiet pointer to /intelligence, not an error.
export function RefreshInsightsButton() {
  const [pending, startTransition] = useTransition();
  const [note, setNote] = useState<string | null>(null);

  const run = () =>
    startTransition(async () => {
      setNote(null);
      // Independent analyses — run them concurrently (sequential worst case
      // froze the button for minutes). daily_briefing is the narration
      // itself: without it this button never actually refreshed the brief.
      const [recovery, correlation, briefing] = await Promise.all([
        triggerAnalysisAction("recovery_check"),
        triggerAnalysisAction("correlation_analysis"),
        triggerAnalysisAction("daily_briefing"),
      ]);
      if (!recovery.ok && !correlation.ok && !briefing.ok) {
        const detail = briefing.error ?? recovery.error ?? correlation.error ?? "";
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
          analyzing…
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
        Refresh
      </button>
    </span>
  );
}
