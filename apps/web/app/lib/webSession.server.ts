import { cookies } from "next/headers";

import { isValidSessionToken, SESSION_COOKIE, sessionCredential } from "./webAuth";

// True when sign-in is off, or the request carries a valid session cookie.
export async function hasWebSession(): Promise<boolean> {
  const credential = sessionCredential();
  if (!credential) return true;
  const jar = await cookies();
  return isValidSessionToken(jar.get(SESSION_COOKIE)?.value, credential);
}

// Server actions check the session themselves instead of trusting the proxy
// alone: an action is a POST to whatever page imports it, so one matcher gap or
// a moved import would otherwise make it callable without signing in.
export async function assertWebSession(): Promise<void> {
  if (!(await hasWebSession())) throw new Error("sign_in_required");
}
