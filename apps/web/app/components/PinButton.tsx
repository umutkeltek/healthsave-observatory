"use client";

import { useTransition } from "react";

import { togglePinAction } from "../lib/actions";

// Pin/unpin a metric onto the Today Signals grid. Server action writes the
// cookie and revalidates; the row re-renders with the new state.
export function PinButton({ metricId, pinned }: { metricId: string; pinned: boolean }) {
  const [pending, startTransition] = useTransition();
  return (
    <button
      type="button"
      className={`pin-btn ${pinned ? "pinned" : ""}`}
      disabled={pending}
      aria-pressed={pinned}
      aria-label={pinned ? "Unpin from Today" : "Pin to Today"}
      title={pinned ? "Unpin from Today" : "Pin to Today"}
      onClick={() => startTransition(() => togglePinAction(metricId).then(() => undefined))}
    >
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden fill={pinned ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round">
        <path d="M8 1.8l1.9 3.9 4.3.6-3.1 3 .7 4.2L8 11.5l-3.8 2 .7-4.2-3.1-3 4.3-.6z" />
      </svg>
    </button>
  );
}
