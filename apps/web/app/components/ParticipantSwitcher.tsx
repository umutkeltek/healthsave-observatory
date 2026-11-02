// Participant switcher for a coach or clinic Observatory (migration 029).
// Server half: renders nothing on a single-person install, so the shell of
// every existing Observatory is unchanged. Streams in via Suspense like the
// sidebar status, so it never blocks the chrome.

import { currentOwner } from "../lib/api";
import { safeOwners } from "../lib/load";
import { DEFAULT_OWNER_ID } from "../lib/participants";
import { ParticipantSelect } from "./ParticipantSelect";

export async function ParticipantSwitcher() {
  const [owners, selected] = await Promise.all([safeOwners(), currentOwner()]);
  if (!owners || owners.length <= 1) return null;
  const current = owners.some((owner) => owner.id === selected) ? (selected as string) : DEFAULT_OWNER_ID;
  return (
    <ParticipantSelect
      current={current}
      owners={owners.map((owner) => ({
        id: owner.id,
        label: owner.label,
        isDefault: owner.is_default,
        active: owner.active,
      }))}
    />
  );
}
