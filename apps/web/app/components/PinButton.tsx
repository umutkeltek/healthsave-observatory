"use client";

import { useState, useTransition } from "react";

import { togglePinAction } from "../lib/actions";
import { runAction } from "../lib/session";
import { useI18n } from "./I18nProvider";

// Pin/unpin a metric onto the Today Signals grid. The server action writes the
// cookie and revalidates; the row re-renders with the new state. A refused pin
// (the grid is full) or a failed write says why under the star.
export function PinButton({ metricId, pinned }: { metricId: string; pinned: boolean }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const { dict } = useI18n();
  return (
    <PinControl
      pinned={pinned}
      pending={pending}
      error={error}
      label={pinned ? dict.explore.unpinFromToday : dict.explore.pinToToday}
      onPick={() => {
        setError(null);
        startTransition(async () => {
          const result = await runAction(() => togglePinAction(metricId));
          if (!result.ok) setError(result.error ?? dict.explore.pinFailed);
        });
      }}
    />
  );
}

// The star and its message as ONE element: the star sits in a grid cell of
// Library rows, and a second element would take the next column.
export function PinControl({
  pinned,
  pending,
  error,
  label,
  onPick,
}: {
  pinned: boolean;
  pending: boolean;
  error: string | null;
  label: string;
  onPick: () => void;
}) {
  return (
    <span className="pin-control">
      <button
        type="button"
        className={`pin-btn ${pinned ? "pinned" : ""}`}
        disabled={pending}
        aria-pressed={pinned}
        aria-label={label}
        title={label}
        onClick={onPick}
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
