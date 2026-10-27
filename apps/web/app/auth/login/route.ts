import { NextResponse } from "next/server";

import {
  configuredWebPassword,
  createSessionToken,
  passwordMatches,
  relativeRedirect,
  requestIsHttps,
  SESSION_COOKIE,
  safeNextPath,
  sessionCookieOptions,
} from "../../lib/webAuth";

export const dynamic = "force-dynamic";

// A fixed pause after a wrong password slows guessing without any server state.
const FAILED_ATTEMPT_DELAY_MS = 750;

// The sign-in form on /login posts here. 303 so the browser follows with a GET.
export async function POST(request: Request) {
  const url = new URL(request.url);
  const form = await request.formData().catch(() => null);
  const candidate = String(form?.get("password") ?? "");
  const next = safeNextPath(String(form?.get("next") ?? "/"));
  const password = configuredWebPassword();

  if (!password) return new NextResponse(null, relativeRedirect(next));

  if (!(await passwordMatches(candidate, password))) {
    await new Promise((resolve) => setTimeout(resolve, FAILED_ATTEMPT_DELAY_MS));
    const retry = new URLSearchParams({ error: "1" });
    if (next !== "/") retry.set("next", next);
    return new NextResponse(null, relativeRedirect(`/login?${retry}`));
  }

  const response = new NextResponse(null, relativeRedirect(next));
  response.cookies.set(
    SESSION_COOKIE,
    await createSessionToken(password),
    sessionCookieOptions(requestIsHttps(url, request.headers.get("x-forwarded-proto"))),
  );
  return response;
}
