import { NextResponse } from "next/server";

import {
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

// A fixed pause after a wrong password, plus the process-wide limiter shared with
// the Settings password forms.
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

  if (passwordAttempts.isBlocked()) {
    return NextResponse.json(
      { detail: "too_many_attempts" },
      { status: 429, headers: { "retry-after": "60", "cache-control": "no-store" } },
    );
  }

  if (!(await verifyWebPassword(candidate))) {
    passwordAttempts.recordFailure();
    await new Promise((resolve) => setTimeout(resolve, FAILED_ATTEMPT_DELAY_MS));
    const retry = new URLSearchParams({ error: "1" });
    if (next !== "/") retry.set("next", next);
    return new NextResponse(null, relativeRedirect(`/login?${retry}`));
  }

  const response = new NextResponse(null, relativeRedirect(next));
  response.cookies.set(
    SESSION_COOKIE,
    await createSessionToken(auth.credential),
    sessionCookieOptions(requestIsHttps(url, request.headers.get("x-forwarded-proto"))),
  );
  return response;
}
