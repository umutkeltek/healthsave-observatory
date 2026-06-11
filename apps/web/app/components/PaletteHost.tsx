import { safeMetrics } from "../lib/load";
import { CommandPalette } from "./CommandPalette";

// Server side of the ⌘K palette: fetch the catalog once (SWR-cached) and hand
// the client island a minimal list. Streams in behind Suspense; while pending
// (or with the backend unreachable) the layout's fallback palette still
// navigates pages.
export async function PaletteHost() {
  const metrics = await safeMetrics();
  return (
    <CommandPalette
      metrics={(metrics ?? []).map((m) => ({
        id: m.id,
        name: m.display_name,
        category: m.category,
      }))}
    />
  );
}
