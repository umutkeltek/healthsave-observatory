"use server";

// Settings -> Web sign-in. These run on the Next server; the password and its
// hash never reach the browser. Each action re-checks the session (see
// webSession.server.ts) and, when a password is in force, the current password.

import { cookies, headers } from "next/headers";

import { getDictionary, signInBlockedMessage } from "./i18n";
import {
  clientAddress,
  createSessionToken,
  isSameOriginPost,
  SESSION_COOKIE,
  sessionCookieOptions,
} from "./webAuth";
import {
  checkNewWebPassword,
  passwordAttempts,
  resolveWebAuth,
  storeWebPassword,
  storeWebSignInOff,
  verifyWebPassword,
} from "./webAuthStore.server";
import { assertWebSession } from "./webSession.server";

export type WebSignInResult = { ok: boolean; error?: string };

async function checkCurrentPassword(current: string): Promise<string | null> {
  const auth = await resolveWebAuth();
  if (auth.mode !== "password") return null;
  const client = clientAddress(await headers());
  const block = passwordAttempts.blocked(client);
  if (block) {
    // The Settings sign-in form (WebSignInSettings) is not in the catalog yet and
    // reads in English; its messages stay in the form's language.
    return signInBlockedMessage(getDictionary("en"), block.scope, block.retryAfterSeconds);
  }
  // Counted before the check and taken back on a match (see recordFailure).
  const attempt = passwordAttempts.recordFailure(client);
  if (!(await verifyWebPassword(current))) return "The current password is not right.";
  passwordAttempts.forgive(client, attempt);
  return null;
}

async function refreshSessionCookie() {
  const auth = await resolveWebAuth();
  if (auth.mode !== "password") return;
  const requestHeaders = await headers();
  const proto = requestHeaders.get("x-forwarded-proto");
  const secure = proto ? proto.split(",")[0].trim().toLowerCase() === "https" : false;
  (await cookies()).set(SESSION_COOKIE, await createSessionToken(auth.credential), sessionCookieOptions(secure));
}

async function guard(): Promise<string | null> {
  await assertWebSession();
  if (!isSameOriginPost(await headers())) return "This request did not come from the dashboard.";
  return null;
}

// Sets the first password, or changes the current one. Saving a password here
// takes over from WEB_PASSWORD in .env.
export async function setWebPasswordAction(input: {
  current?: string;
  next: string;
  confirm: string;
}): Promise<WebSignInResult> {
  const blocked = await guard();
  if (blocked) return { ok: false, error: blocked };
  const currentError = await checkCurrentPassword(input.current ?? "");
  if (currentError) return { ok: false, error: currentError };
  const invalid = checkNewWebPassword(input.next ?? "", input.confirm ?? "");
  if (invalid) return { ok: false, error: invalid };
  try {
    await storeWebPassword(input.next);
    await refreshSessionCookie();
    return { ok: true };
  } catch {
    return { ok: false, error: "Could not save the password. Check that the web container's data volume is writable." };
  }
}

// Turns sign-in off (passwordless). Needs the current password.
export async function turnOffWebSignInAction(input: { current: string }): Promise<WebSignInResult> {
  const blocked = await guard();
  if (blocked) return { ok: false, error: blocked };
  const currentError = await checkCurrentPassword(input.current ?? "");
  if (currentError) return { ok: false, error: currentError };
  try {
    await storeWebSignInOff();
    return { ok: true };
  } catch {
    return { ok: false, error: "Could not save the setting. Check that the web container's data volume is writable." };
  }
}
