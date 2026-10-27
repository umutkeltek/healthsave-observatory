import { NextResponse } from "next/server";

import {
  isSameOriginPost,
  relativeRedirect,
  requestIsHttps,
  SESSION_COOKIE,
  sessionCookieOptions,
} from "../../lib/webAuth";

export const dynamic = "force-dynamic";

// POST only, and only from this site's own pages, so another page (or another
// service on the same host) cannot sign you out.
export async function POST(request: Request) {
  if (!isSameOriginPost(request.headers)) {
    return NextResponse.json({ detail: "cross_site_request" }, { status: 403 });
  }
  const url = new URL(request.url);
  const response = new NextResponse(null, relativeRedirect("/login"));
  response.cookies.set(
    SESSION_COOKIE,
    "",
    sessionCookieOptions(requestIsHttps(url, request.headers.get("x-forwarded-proto")), 0),
  );
  return response;
}
