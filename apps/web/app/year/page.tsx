import type { Metadata } from "next";

import YearPage from "./[year]/page";

// /year shows the current year in place (a redirect from inside the streamed
// shell would arrive as a one-second meta refresh).
export const metadata: Metadata = { title: "Year in Health · HealthSave Observatory" };
export const dynamic = "force-dynamic";

export default function YearIndex({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return YearPage({ params: Promise.resolve({ year: String(new Date().getUTCFullYear()) }), searchParams });
}
