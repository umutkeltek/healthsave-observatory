// The Year in Health share card as SVG, drawn on this server from the year's
// API summary. Opt-ins (numbers=1, devices=1) come from the page; without them
// the card carries the shape of the year and the year itself, nothing else.

import { safeYear } from "../../../lib/load";
import { parseYearParam } from "../../../lib/year";
import { parseCardOptions, renderYearCard } from "../../../lib/yearCard";

export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ year: string }> }): Promise<Response> {
  const { year: raw } = await params;
  const year = parseYearParam(raw);
  if (year === null) return Response.json({ detail: "unknown year" }, { status: 404 });
  const summary = await safeYear(year);
  if (!summary) return Response.json({ detail: "year_unavailable" }, { status: 502 });
  const url = new URL(request.url);
  const headers: Record<string, string> = {
    "Content-Type": "image/svg+xml; charset=utf-8",
    // One person's card: never shared through a cache.
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
  };
  if (url.searchParams.get("download") === "1") {
    headers["Content-Disposition"] = `attachment; filename="year-in-health-${year}.svg"`;
  }
  return new Response(renderYearCard(summary, parseCardOptions(url.searchParams)), { headers });
}
