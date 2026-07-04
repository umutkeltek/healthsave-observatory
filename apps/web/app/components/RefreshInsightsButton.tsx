"use client";

import { useState, useTransition } from "react";

import { triggerAnalysisAction } from "../lib/actions";

// Refresh the visible brief plus supporting checks. The UI calls this a brief,
// not narration, because users do not need to know the internal job names.
export function RefreshInsightsButton() {
  const [pending, startTransition] = useTransition();
  const [note, setNote] = useState<string | null>(null);

  // Prefer the weekly brief, then fall back to today's briefing when weekly is disabled.
  const runBriefing = async () => {
    const weekly = await triggerAnalysisAction("weekly_summary");
    if (weekly.ok || !(weekly.error ?? "").includes("disabled")) return weekly;
    return triggerAnalysisAction("daily_briefing");
  };

  const run = () =>
    startTransition(async () => {
      setNote(null);

      const [recovery, correlation, briefing] = await Promise.all([
        triggerAnalysisAction("recovery_check"),
        triggerAnalysisAction("correlation_analysis"),
        runBriefing(),
      ]);

      if (!briefing.ok) {
        const detail = briefing.error ?? "";
        setNote(
          detail.includes("disabled")
            ? "Briefs are off - enable them under Intelligence."
            : `Brief did not refresh${detail ? `: ${detail}` : "."}`,
        );
      } else if (!recovery.ok || !correlation.ok) {
        setNote("Some checks did not finish. Try refreshing again.");
      } else {
        setNote(null);
      }
    });

  return (
    <span className="brief-refresh">
      {pending && (
        <span className="brief-narrating mono" aria-live="polite">
          <span className="live-dot" aria-hidden />
          analyzing...
        </span>
      )}
      {!pending && note && (
        <span className="brief-note mono">
          {note.includes("Intelligence") ? <>Briefs are off. <a href="/intelligence">Enable them</a>.</> : note}
        </span>
      )}
      <button type="button" className="btn btn-ghost" disabled={pending} onClick={run}>
        Refresh
      </button>
    </span>
  );
}
