import type { Metadata } from "next";

import { YearView } from "../components/YearView";
import { loadYear } from "../lib/load";
import { parseCardOptions } from "../lib/yearCard";

// /year shows the person's current year in place. The server's clock may be
// ahead of the person's day (New Year in another time zone, or before the
// 04:00 day start), so a year that has not started falls back to the one
// before instead of looking like an outage.
export const metadata: Metadata = { title: "Year in Health · HealthSave Observatory" };
export const dynamic = "force-dynamic";

export default async function YearIndex({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  let year = new Date().getUTCFullYear();
  let loaded = await loadYear(year);
  if (loaded.notStarted) {
    year -= 1;
    loaded = await loadYear(year);
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (first !== undefined) params.set(key, first);
  }
  return <YearView year={year} summary={loaded.summary} notStarted={loaded.notStarted} options={parseCardOptions(params)} />;
}
