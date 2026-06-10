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

  // The narration itself: prefer the weekly brief (the card's namesake; the
  // only narrator job on a weekly-only live config), fall back to the daily
  // briefing when weekly is disabled. The 409 probe costs nothing — the
  // fallback never runs two narrations.
  const runBriefing = async () => {
    const weekly = await triggerAnalysisAction("weekly_summary");
    if (weekly.ok || !(weekly.error ?? "").includes("disabled")) return weekly;
    return triggerAnalysisAction("daily_briefing");
  };

  const run = () =>
    startTransition(async () => {
      setNote(null);
      // Independent analyses — run them concurrently (sequential worst case
      // froze the button for minutes). Without the briefing trigger this
      // button never actually refreshed the brief it sits on.
      const [recovery, correlation, briefing] = await Promise.all([
        triggerAnalysisAction("recovery_check"),
        triggerAnalysisAction("correlation_analysis"),
        runBriefing(),
      ]);
      // The briefing IS this card — its failure must surface even when the
      // finding jobs succeeded (a swallowed brief error is the exact silent
      // failure this card is meant to expose).
      if (!briefing.ok) {
        const detail = briefing.error ?? "";
        setNote(
          detail.includes("disabled")
            ? "Narration is off — enable it under Intelligence."
            : `Brief didn't regenerate${detail ? `: ${detail}` : "."}`,
        );
      } else if (!recovery.ok && !correlation.ok) {
        const detail = recovery.error ?? correlation.error ?? "";
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
              {note.startsWith("Narration") ? "Narration" : "Analysis"} is off —{" "}
              <a href="/intelligence">enable it</a>.
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
