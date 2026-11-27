// Participant switcher for a coach or clinic Observatory (migration 029).
// Server half. It takes who is being viewed from participantView, the same
// decision every read uses, so the name shown and the data under it agree. On a
// single-person install with no participant cookie it renders nothing visible.
// Streams in via Suspense like the sidebar status, so it never blocks the chrome.

import { participantView } from "../lib/api";
import { safeOwners } from "../lib/load";
import { switcherModel } from "../lib/participants";
import { ParticipantSelect } from "./ParticipantSelect";

export async function ParticipantSwitcher() {
  const { person, owners: listed } = await participantView();
  // With no participant cookie the decision did not need the owner list; the
  // select still needs it to offer someone else.
  const owners = person.kind === "primary" ? await safeOwners() : listed;
  const model = switcherModel(person, owners);
  // Always the same client component, even when it shows nothing: it keeps the
  // "no longer on this Observatory" note across the refresh that clearing the
  // cookie causes, and it listens for a switch made in another tab.
  return (
    <ParticipantSelect
      owners={model.options}
      current={model.current}
      notice={model.notice}
      clearCookie={model.clearCookie}
    />
  );
}
