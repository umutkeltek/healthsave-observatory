import { Suspense } from "react";

import { safeMetrics } from "../lib/load";
import { CommandPalette, PaletteCatalog } from "./CommandPalette";

// The palette the shell renders: one client instance from the first paint,
// which navigates pages at once and gains the signal catalog when it streams
// in (or never, with the backend unreachable). Only the catalog waits, so a
// palette opened early stays open.
export function ShellPalette() {
  return (
    <CommandPalette
      catalog={
        <Suspense fallback={null}>
          <PaletteHost />
        </Suspense>
      }
    />
  );
}

// Server side of the ⌘K palette: fetch the catalog once (SWR-cached) and hand
// the client island a minimal list.
export async function PaletteHost() {
  const metrics = await safeMetrics();
  return (
    <PaletteCatalog
      metrics={(metrics ?? []).map((m) => ({
        id: m.id,
        name: m.display_name,
        category: m.category,
      }))}
    />
  );
}
