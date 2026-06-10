// Cookie-backed user preferences, read server-side so every page renders the
// right mode with zero hydration flash. Written only by the server actions in
// actions.ts.

import { cookies } from "next/headers";

export type Density = "essentials" | "observatory";

export const DENSITY_COOKIE = "density";
export const PINNED_COOKIE = "pinned_metrics";
export const MAX_PINS = 16;

export async function getDensity(): Promise<Density> {
  const jar = await cookies();
  return jar.get(DENSITY_COOKIE)?.value === "observatory" ? "observatory" : "essentials";
}

export function parsePinned(raw: string | undefined): string[] {
  if (!raw) return [];
  try {
    const arr = JSON.parse(raw);
    return Array.isArray(arr)
      ? arr.filter((x): x is string => typeof x === "string").slice(0, MAX_PINS)
      : [];
  } catch {
    return [];
  }
}

export async function getPinnedMetrics(): Promise<string[]> {
  const jar = await cookies();
  return parsePinned(jar.get(PINNED_COOKIE)?.value);
}
