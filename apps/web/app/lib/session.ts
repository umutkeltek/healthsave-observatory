// What an expired web session looks like from the browser, in one place.
//
// The proxy answers a server action that has no valid session with a 401 whose
// text/plain body is "sign_in_required". Next's action client turns such a body
// into the message of the error the action call rejects with, so the page can
// tell "signed out" apart from a real bug. The live poll sees the same 401 on
// /api/changes. Both show the person a way to sign in again instead of
// "offline" or the UI-bug card.

import { dictionaries } from "./i18n";

export const SIGN_IN_REQUIRED = "sign_in_required";

// Fired in the browser when an action finds the session gone, so the top bar
// shows "signed out" at once instead of at the next poll.
export const SIGNED_OUT_EVENT = "healthsave:signed-out";

// Shown where an action failed, at any width: phones hide the top bar's
// "sign in" pill, so the message names the sign-in page itself. The text lives
// in lib/i18n; English pages show this, a translated surface (the participant
// switcher) passes its own dictionary's to runAction.
export const SIGNED_OUT_MESSAGE: string = dictionaries.en.session.signedOut;

export function isSignInRequired(error: unknown): boolean {
  return error instanceof Error && error.message === SIGN_IN_REQUIRED;
}

export function signInPath(next: string): string {
  return next && next !== "/" ? `/login?next=${encodeURIComponent(next)}` : "/login";
}

export function announceSignedOut(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
}

/**
 * Runs a server action. A sign-in rejection comes back as an ordinary failed
 * result, so the caller shows it like any other failure and keeps what was
 * typed; every other rejection is rethrown for the error boundary.
 *
 * The cast holds because every action result beyond `ok`/`error` is optional.
 */
export async function runAction<T extends { ok: boolean; error?: string }>(
  action: () => Promise<T>,
  signedOutMessage: string = SIGNED_OUT_MESSAGE,
): Promise<T> {
  try {
    return await action();
  } catch (error) {
    if (!isSignInRequired(error)) throw error;
    announceSignedOut();
    return { ok: false, error: signedOutMessage } as T;
  }
}

export type PollState = "unknown" | "live" | "offline" | "signed-out";

/** The live poll's state for one /api/changes answer (null = no response). */
export function pollState(status: number | null, wasLive: boolean): PollState {
  if (status === 200 || status === 304) return "live";
  if (status === 401) return "signed-out";
  return wasLive ? "offline" : "unknown";
}
