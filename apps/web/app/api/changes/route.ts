// Browser-facing proxy for the backend's change fingerprint. The X-API-Key
// never reaches the browser - the LiveStatus poller hits this route and the
// key is injected server-side. ETag/304 semantics pass straight through, so
// an unchanged state costs a header exchange and nothing more.

import { clearSwrCache } from "../../lib/ttlCache";

export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";
const API_KEY = process.env.API_KEY ?? "";

export async function GET(request: Request): Promise<Response> {
  const headers: Record<string, string> = {};
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const inm = request.headers.get("if-none-match");
  if (inm) headers["If-None-Match"] = inm;

  try {
    const res = await fetch(`${API_BASE}/api/v2/changes`, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (res.status === 304) {
      return new Response(null, { status: 304, headers: inm ? { ETag: inm } : undefined });
    }
    if (!res.ok) {
      return Response.json({ error: `backend ${res.status}` }, { status: 502 });
    }
    const body = await res.json();
    const etag = res.headers.get("etag");
    // A 200 after the browser supplied an ETag means the backend fingerprint
    // changed. Drop process-level SWR entries before LiveStatus refreshes the
    // route, otherwise router.refresh() can keep serving stale values until
    // each entry's independent TTL expires.
    if (inm && etag && etag !== inm) clearSwrCache();
    return Response.json(body, { headers: etag ? { ETag: etag } : undefined });
  } catch {
    return Response.json({ error: "backend unreachable" }, { status: 502 });
  }
}
