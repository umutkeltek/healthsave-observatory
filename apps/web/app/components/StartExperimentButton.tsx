"use client";

import { useState, useTransition } from "react";

import { startExperimentAction } from "../lib/actions";

// Promotes a testable candidate into a committed experiment. Calls the server
// action (key stays server-side); shows pending + any backend error inline.
export function StartExperimentButton({ lever, outcome }: { lever: string; outcome: string }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="exp-action">
      <button
        type="button"
        className="btn"
        disabled={pending}
        onClick={() =>
          startTransition(async () => {
            const result = await startExperimentAction(lever, outcome);
            setError(result.ok ? null : (result.error ?? "Could not start the experiment."));
          })
        }
      >
        {pending ? "Starting…" : "Start experiment"}
      </button>
      {error && <span className="exp-error">{error}</span>}
    </div>
  );
}
