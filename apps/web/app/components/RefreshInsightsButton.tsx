"use client";

import { useState, useTransition } from "react";

import { type TriggerAnalysisResult, type TriggerOutcome, triggerAnalysisAction } from "../lib/actions";
import { runAction } from "../lib/session";

// What the last refresh said, decided from each trigger's outcome - never from
// the wording of an error.
export type RefreshNote = { kind: "briefs-off" } | { kind: "message"; text: string } | null;

// A result without an outcome came from outside the action (a signed-out
// session, say): a failure if not ok.
function outcomeOf(result: TriggerAnalysisResult): TriggerOutcome {
  return result.outcome ?? (result.ok ? "completed" : "failed");
}

/** Today's briefing stands in only when the weekly brief is switched off. */
export function needsDailyFallback(weekly: TriggerAnalysisResult): boolean {
  return outcomeOf(weekly) === "disabled";
}

export function refreshNote(
  recovery: TriggerAnalysisResult,
  correlation: TriggerAnalysisResult,
  briefing: TriggerAnalysisResult,
): RefreshNote {
  switch (outcomeOf(briefing)) {
    case "disabled":
      return { kind: "briefs-off" };
    case "failed":
      return { kind: "message", text: `Brief did not refresh${briefing.error ? `: ${briefing.error}` : "."}` };
    case "skipped":
      return { kind: "message", text: "No new brief yet - there was nothing new to write." };
    case "completed":
      return [recovery, correlation].some((result) => outcomeOf(result) === "failed")
        ? { kind: "message", text: "Some checks did not finish. Try refreshing again." }
        : null;
  }
}

// Refresh the visible brief plus its supporting checks. The UI calls this the
// brief, not narration, because users do not need to know internal job names.
export function RefreshInsightsButton() {
  const [pending, startTransition] = useTransition();
  const [note, setNote] = useState<RefreshNote>(null);

  const trigger = (type: Parameters<typeof triggerAnalysisAction>[0]) =>
    runAction(() => triggerAnalysisAction(type));

  // Prefer the weekly brief, then fall back to today's briefing when weekly is disabled.
  const runBriefing = async () => {
    const weekly = await trigger("weekly_summary");
    return needsDailyFallback(weekly) ? trigger("daily_briefing") : weekly;
  };

  const run = () =>
    startTransition(async () => {
      setNote(null);
      const [recovery, correlation, briefing] = await Promise.all([
        trigger("recovery_check"),
        trigger("correlation_analysis"),
        runBriefing(),
      ]);
      setNote(refreshNote(recovery, correlation, briefing));
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
          {note.kind === "briefs-off" ? (
            <>
              Briefs are off. <a href="/intelligence">Enable them</a>.
            </>
          ) : (
            note.text
          )}
        </span>
      )}
      <button type="button" className="btn btn-ghost" disabled={pending} onClick={run}>
        Refresh
      </button>
    </span>
  );
}
