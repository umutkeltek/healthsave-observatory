// Liveness probe target for the container healthcheck. A bare 200 with no data
// fetching and no layout render, so it answers instantly even when a full page
// (e.g. the Today SSR) takes several seconds to assemble from the backend API.
// The container probe hits this instead of `/` — see apps/web/Dockerfile.
export const dynamic = "force-dynamic";

export function GET() {
  return new Response("ok", {
    status: 200,
    headers: { "content-type": "text/plain", "cache-control": "no-store" },
  });
}
