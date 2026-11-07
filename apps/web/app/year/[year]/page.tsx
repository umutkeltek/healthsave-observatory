import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { YearView } from "../../components/YearView";
import { loadYear } from "../../lib/load";
import { parseYearParam } from "../../lib/year";
import { parseCardOptions } from "../../lib/yearCard";

export const metadata: Metadata = { title: "Year in Health · HealthSave Observatory" };
export const dynamic = "force-dynamic";

type Params = { year: string };
type SearchParams = Record<string, string | string[] | undefined>;

function toSearchParams(sp: SearchParams): URLSearchParams {
  const out = new URLSearchParams();
  for (const [key, value] of Object.entries(sp)) {
    const first = Array.isArray(value) ? value[0] : value;
    if (first !== undefined) out.set(key, first);
  }
  return out;
}

export default async function YearPage({
  params,
  searchParams,
}: {
  params: Promise<Params>;
  searchParams: Promise<SearchParams>;
}) {
  const { year: raw } = await params;
  const year = parseYearParam(raw);
  if (year === null) notFound();
  const [loaded, sp] = await Promise.all([loadYear(year), searchParams]);
  return (
    <YearView
      year={year}
      summary={loaded.summary}
      notStarted={loaded.notStarted}
      options={parseCardOptions(toSearchParams(sp))}
    />
  );
}
