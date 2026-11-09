"use client";

import { useState, useTransition } from "react";

import { togglePinAction } from "../lib/actions";
import { runAction } from "../lib/session";
import { useI18n } from "./I18nProvider";

// Pin/unpin a metric onto the Today Signals grid. The server action writes the
// cookie and revalidates; the row re-renders with the new state. A refused pin
// (the grid is full) or a failed write says why under the star; one wrapper
// element, so the rows it sits in keep their grid columns.
export function PinButton({ metricId, pinned }: { metricId: string; pinned: boolean }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const { dict } = useI18n();
  const label = pinned ? dict.explore.unpinFromToday : dict.explore.pinToToday;
  return (
    <span className="pin-control">
      <button
        type="button"
        className={`pin-btn ${pinned ? "pinned" : ""}`}
        disabled={pending}
        aria-pressed={pinned}
        aria-label={label}
        title={label}
        onClick={() => {
          setError(null);
          startTransition(async () => {
            const result = await runAction(() => togglePinAction(metricId));
            if (!result.ok) setError(result.error ?? dict.explore.pinFailed);
          });
        }}
      >
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden fill={pinned ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round">
          <path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.2L8 11.5l-3.8 2 .7-4.2-3.1-3 4.3-.6z" />
        </svg>
      </button>
      {error ? (
        <span className="pin-error" role="status">
          {error}
        </span>
      ) : null}
    </span>
  );
}
