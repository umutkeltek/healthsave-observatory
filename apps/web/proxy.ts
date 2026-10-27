import { type NextRequest, NextResponse } from "next/server";

import { BARE_LAYOUT_HEADER, isPublicRequest, isValidSessionToken, SESSION_COOKIE } from "./app/lib/webAuth";
import { resolveWebAuth } from "./app/lib/webAuthStore.server";

// Every request except hashed build assets passes through here: pages, server
// actions, route handlers, the /api rewrite, and paths that only 404. Without a
// valid session cookie a page request goes to /login and anything else gets 401.
// With sign-in off (no password in Settings or .env), requests pass as before;
// see app/lib/webAuthStore.server.ts for where the setting comes from.
export async function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.delete(BARE_LAYOUT_HEADER);

  const auth = await resolveWebAuth();
  const { pathname, search } = request.nextUrl;
  const method = request.method;

  if (auth.mode === "unreadable" && pathname !== "/api/health") {
    return NextResponse.json(
      { detail: "web_sign_in_settings_unreadable: fix or delete data/web-auth.json (healthsave web-password reset)" },
      { status: 503 },
    );
  }
  const credential = auth.credential;
  if (pathname === "/login" && (method === "GET" || method === "HEAD")) headers.set(BARE_LAYOUT_HEADER, "1");
  if (!credential || isPublicRequest(pathname, method)) {
    return NextResponse.next({ request: { headers } });
  }

  if (await isValidSessionToken(request.cookies.get(SESSION_COOKIE)?.value, credential)) {
    return NextResponse.next({ request: { headers } });
  }

  const isPageNavigation =
    (method === "GET" || method === "HEAD") && !pathname.startsWith("/api/") && !request.headers.has("next-action");
  if (isPageNavigation) {
    // Proxy redirects must be absolute; Next sends a same-origin one to the
    // browser as a relative Location, so the LAN hostname is kept.
    const login = new URL("/login", request.url);
    if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }
  return NextResponse.json({ detail: "sign_in_required" }, { status: 401 });
}

// Only content-hashed build output skips the check. A prefix-style exclusion such
// as "favicon.ico" would also let "/favicon.ico.x" through to a 404 page rendered
// inside the shell, which reads health data.
export const config = {
  matcher: ["/((?!_next/static/).*)"],
};
