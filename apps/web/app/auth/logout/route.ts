import { NextResponse } from "next/server";

import { relativeRedirect, requestIsHttps, SESSION_COOKIE, sessionCookieOptions } from "../../lib/webAuth";

export const dynamic = "force-dynamic";

// POST only, so a link or image on another page cannot sign you out.
export async function POST(request: Request) {
  const url = new URL(request.url);
  const response = new NextResponse(null, relativeRedirect("/login"));
  response.cookies.set(
    SESSION_COOKIE,
    "",
    sessionCookieOptions(requestIsHttps(url, request.headers.get("x-forwarded-proto")), 0),
  );
  return response;
}
