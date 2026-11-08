"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useOptimistic, useState, useTransition } from "react";

import { setParticipantAction } from "../lib/actions";
import { DEFAULT_OWNER_ID, type ParticipantNotice, type ParticipantOption } from "../lib/participants";
import { useI18n } from "./I18nProvider";

export type { ParticipantOption };

// Tabs share the participant cookie, but a tab only re-reads its shell on a
// refresh: a switch in one tab tells the others to refresh.
const SWITCH_CHANNEL = "healthsave-participant";

// Client half of the participant switcher: a plain labelled select (the same
// control grammar as the Explore filters), then a router refresh so every
// server-rendered card re-reads for the chosen person. `current` comes from the
// server's decision; the only local copy is the optimistic value while a switch
// is in flight, which falls back to `current` when it ends.
export function ParticipantSelect({
  owners,
  current,
  notice = null,
  clearCookie = false,
}: {
  owners: ParticipantOption[];
  current: string;
  notice?: ParticipantNotice;
  clearCookie?: boolean;
}) {
  const { dict } = useI18n();
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [shown, setShown] = useOptimistic(current);
  const [error, setError] = useState<string | null>(null);
  // Clearing the cookie re-renders the shell without the notice; keep saying
  // why the view moved to the primary person until the person picks again.
  const [movedToPrimary, setMovedToPrimary] = useState(notice === "unlisted");
  const noteId = useId();
  const viewingParticipant = shown !== DEFAULT_OWNER_ID;

  useEffect(() => {
    if (!clearCookie) return;
    setMovedToPrimary(true);
    // Reads already go to the primary person; this only drops the stale cookie.
    setParticipantAction(DEFAULT_OWNER_ID).catch(() => {});
  }, [clearCookie]);

  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(SWITCH_CHANNEL);
    channel.onmessage = () => router.refresh();
    return () => channel.close();
  }, [router]);

  const name = (owner: ParticipantOption) => {
    if (owner.isDefault) return dict.participants.primary;
    const label = owner.label ?? owner.id.slice(0, 8);
    return owner.active ? label : `${label} (${dict.participants.revoked})`;
  };

  const note = error
    ? error
    : movedToPrimary
      ? dict.participants.unlisted
      : notice === "unverified"
        ? dict.participants.unverified
        : viewingParticipant
          ? dict.participants.primaryOnly
          : null;

  if (owners.length === 0) {
    return note ? (
      <div className="participant-switcher">
        <p className="participant-note" role="status">
          {note}
        </p>
      </div>
    ) : null;
  }

  return (
    <div className="participant-switcher">
      <label className="filter-label" htmlFor={`${noteId}-select`}>
        {dict.participants.label}
      </label>
      <select
        id={`${noteId}-select`}
        className="filter-select participant-select"
        value={shown}
        disabled={pending}
        aria-busy={pending}
        aria-describedby={note ? noteId : undefined}
        onChange={(event) => {
          const next = event.target.value;
          setError(null);
          setMovedToPrimary(false);
          startTransition(async () => {
            setShown(next);
            const result = await setParticipantAction(next);
            if (!result.ok) {
              setError(result.error ?? null);
              return;
            }
            if (typeof BroadcastChannel !== "undefined") {
              const channel = new BroadcastChannel(SWITCH_CHANNEL);
              channel.postMessage("switched");
              channel.close();
            }
            router.refresh();
          });
        }}
      >
        {owners.map((owner) => (
          <option key={owner.id} value={owner.id}>
            {name(owner)}
          </option>
        ))}
      </select>
      {note ? (
        <p id={noteId} className="participant-note" role="status" aria-live="polite">
          {note}
        </p>
      ) : null}
    </div>
  );
}
