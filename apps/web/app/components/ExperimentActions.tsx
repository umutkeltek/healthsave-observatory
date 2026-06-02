"use client";

import { useState, useTransition } from "react";

import type { ActionResult } from "../lib/actions";
import { abandonExperimentAction, analyzeExperimentAction } from "../lib/actions";

// Analyze / Stop controls for a running experiment. Analyze recomputes the
// controlled ABAB result now (and auto-completes once the window has elapsed);
// Stop abandons a still-collecting experiment.
export function ExperimentActions({ id, status }: { id: string; status: string }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const run = (action: () => Promise<ActionResult>) =>
    startTransition(async () => {
      const result = await action();
      setError(result.ok ? null : (result.error ?? "Action failed."));
    });

  if (status === "abandoned") return null;

  return (
    <div className="exp-action">
      <button
        type="button"
        className="btn"
        disabled={pending}
        onClick={() => run(() => analyzeExperimentAction(id))}
      >
        {pending ? "Working…" : "Analyze now"}
      </button>
      {status === "collecting" && (
        <button
          type="button"
          className="btn btn-ghost"
          disabled={pending}
          onClick={() => run(() => abandonExperimentAction(id))}
        >
          Stop
        </button>
      )}
      {error && <span className="exp-error">{error}</span>}
    </div>
  );
}
