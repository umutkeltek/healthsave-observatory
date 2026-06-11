// Browser-facing proxy for /api/v2/export — the X-API-Key never reaches the
// browser (the /api/changes idiom, applied to file downloads). Params are
// whitelisted and re-validated here so the route can't be steered anywhere
// but the one upstream endpoint; the backend enforces its own row cap.

export const dynamic = "force-dynamic";

const API_BASE = process.env.API_BASE ?? "http://localhost:8000";
const API_KEY = process.env.API_KEY ?? "";

// Legacy public export names (heart_rate, hrv, …) or the literal "all".
const METRIC_RE = /^[a-z][a-z0-9_]{0,63}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const DAYS = new Set(["7", "30", "90", "365"]);

export async function GET(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const metric = url.searchParams.get("metric") ?? "";
  const format = url.searchParams.get("format") === "csv" ? "csv" : "json";
  const days = url.searchParams.get("days") ?? "";
  const from = url.searchParams.get("from") ?? "";
  const to = url.searchParams.get("to") ?? "";

  if (metric !== "all" && !METRIC_RE.test(metric)) {
    return Response.json({ error: "unknown metric" }, { status: 422 });
  }
  if (metric === "all" && format === "csv") {
    return Response.json({ error: "CSV exports one metric at a time" }, { status: 422 });
  }

  const qs = new URLSearchParams({ metric, format });
  if (DAYS.has(days)) qs.set("days", days);
  if (DATE_RE.test(from)) qs.set("from", from);
  if (DATE_RE.test(to)) qs.set("to", to);

  const headers: Record<string, string> = {};
  if (API_KEY) headers["X-API-Key"] = API_KEY;

  try {
    // Exports can legitimately take a while at the 100k row cap.
    const res = await fetch(`${API_BASE}/api/v2/export?${qs}`, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
    if (!res.ok) {
      // 404 unknown-metric / 422 bad-params pass through; everything else is
      // an upstream failure the browser shouldn't mistake for its own request.
      const status = res.status === 404 || res.status === 422 ? res.status : 502;
      return Response.json({ error: `backend ${res.status}` }, { status });
    }
    const out = new Headers();
    out.set("Content-Type", res.headers.get("content-type") ?? "application/json");
    // The backend only sets a filename for CSV — name JSON downloads here.
    out.set(
      "Content-Disposition",
      res.headers.get("content-disposition") ?? `attachment; filename=healthsave_${metric}.json`,
    );
    return new Response(res.body, { headers: out });
  } catch {
    return Response.json({ error: "backend unreachable" }, { status: 502 });
  }
}
