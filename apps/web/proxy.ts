import { type NextRequest, NextResponse } from "next/server";

import {
  BARE_LAYOUT_HEADER,
  configuredWebPassword,
  isPublicPath,
  isValidSessionToken,
  SESSION_COOKIE,
} from "./app/lib/webAuth";

// Every page, server action, route handler and /api rewrite passes through here.
// Without a valid session cookie a page request goes to /login and anything else
// gets 401. With WEB_PASSWORD unset, requests pass as before (see app/lib/webAuth.ts).
export async function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete(BARE_LAYOUT_HEADER);

  const password = configuredWebPassword();
  const { pathname, search } = request.nextUrl;

  if (pathname === "/login") headers.set(BARE_LAYOUT_HEADER, "1");
  if (!password || isPublicPath(pathname)) {
    return NextResponse.next({ request: { headers } });
  }

  if (await isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value, password)) {
    return NextResponse.next({ request: { headers } });
  }

  const isPageNavigation =
    (request.method === "GET" || request.method === "HEAD") &&
    !pathname.startsWith("/api/") &&
    !request.headers.has("next-action");
  if (isPageNavigation) {
    const login = new URL("/login", request.url);
    if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }
  return NextResponse.json({ detail: "sign_in_required" }, { status: 401 });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icon.svg|favicon.ico).*)"],
};
