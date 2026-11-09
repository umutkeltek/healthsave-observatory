import { NextResponse } from "next/server";

import {
  clientAddress,
  createSessionToken,
  isSameOriginPost,
  relativeRedirect,
  requestIsHttps,
  SESSION_COOKIE,
  safeNextPath,
  sessionCookieOptions,
} from "../../lib/webAuth";
import { passwordAttempts, resolveWebAuth, verifyWebPassword } from "../../lib/webAuthStore.server";

export const dynamic = "force-dynamic";

// A fixed pause after a wrong password, plus the limiter shared with the Settings
// password forms: per client address, under a process-wide ceiling.
const FAILED_ATTEMPT_DELAY_MS = 750;

// The sign-in form on /login posts here. 303 so the browser follows with a GET.
export async function POST(request: Request) {
  if (!isSameOriginPost(request.headers)) {
    return NextResponse.json({ detail: "cross_site_request" }, { status: 403 });
  }

  const url = new URL(request.url);
  const form = await request.formData().catch(() => null);
  const candidate = String(form?.get("password") ?? "");
  const next = safeNextPath(String(form?.get("next") ?? "/"));
  const auth = await resolveWebAuth();

  if (auth.mode !== "password") return new NextResponse(null, relativeRedirect(next));

  // The form is a plain browser POST: every outcome goes back to a page the
  // person can read, never a JSON body.
  const backToSignIn = (params: Record<string, string>) => {
    const retry = new URLSearchParams(params);
    if (next !== "/") retry.set("next", next);
    return `/login?${retry}`;
  };

  const client = clientAddress(request.headers);
  const block = passwordAttempts.blocked(client);
  if (block) {
    // "locked": this address guessed too often; "paused": everyone waits.
    const wait = String(block.retryAfterSeconds);
    const init = relativeRedirect(backToSignIn({ error: block.scope === "everyone" ? "paused" : "locked", wait }));
    return new NextResponse(null, { ...init, headers: { ...init.headers, "retry-after": wait } });
  }

  // Counted before the check and taken back on a match (see recordFailure).
  const attempt = passwordAttempts.recordFailure(client);
  if (!(await verifyWebPassword(candidate))) {
    await new Promise((resolve) => setTimeout(resolve, FAILED_ATTEMPT_DELAY_MS));
    return new NextResponse(null, relativeRedirect(backToSignIn({ error: "1" })));
  }
  passwordAttempts.forgive(client, attempt);

  const response = new NextResponse(null, relativeRedirect(next));
  response.cookies.set(
    SESSION_COOKIE,
    await createSessionToken(auth.credential),
    sessionCookieOptions(requestIsHttps(url, request.headers.get("x-forwarded-proto"))),
  );
  return response;
}
