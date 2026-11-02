"use client";

import { useRouter } from "next/navigation";
import { useId, useState, useTransition } from "react";

import { setParticipantAction } from "../lib/actions";
import { DEFAULT_OWNER_ID } from "../lib/participants";
import { useI18n } from "./I18nProvider";

export type ParticipantOption = {
  id: string;
  label: string | null;
  isDefault: boolean;
  active: boolean;
};

// Client half of the participant switcher: a plain labelled select (the same
// control grammar as the Explore filters), then a router refresh so every
// server-rendered card re-reads for the chosen person.
export function ParticipantSelect({
  owners,
  current,
}: {
  owners: ParticipantOption[];
  current: string;
}) {
  const { dict } = useI18n();
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [shown, setShown] = useState(current);
  const [error, setError] = useState<string | null>(null);
  const noteId = useId();
  const viewingParticipant = shown !== DEFAULT_OWNER_ID;

  const name = (owner: ParticipantOption) => {
    if (owner.isDefault) return dict.participants.primary;
    const label = owner.label ?? owner.id.slice(0, 8);
    return owner.active ? label : `${label} (${dict.participants.revoked})`;
  };

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
        aria-describedby={viewingParticipant || error ? noteId : undefined}
        onChange={(event) => {
          const next = event.target.value;
          const previous = shown;
          setShown(next);
          setError(null);
          startTransition(async () => {
            const result = await setParticipantAction(next);
            if (!result.ok) {
              setShown(previous);
              setError(result.error ?? null);
              return;
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
      {error ? (
        <p id={noteId} className="participant-note" role="status" aria-live="polite">
          {error}
        </p>
      ) : viewingParticipant ? (
        <p id={noteId} className="participant-note">
          {dict.participants.primaryOnly}
        </p>
      ) : null}
    </div>
  );
}
