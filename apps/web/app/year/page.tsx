import { redirect } from "next/navigation";

// /year opens the current year.
export const dynamic = "force-dynamic";

export default function YearIndex() {
  redirect(`/year/${new Date().getUTCFullYear()}`);
}
