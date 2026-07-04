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
  // Default to Observatory so every surface is discoverable; Essentials is an
  // explicit opt-in to a calmer, daily-only nav.
  return jar.get(DENSITY_COOKIE)?.value === "essentials" ? "essentials" : "observatory";
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

// ── Focus goal (v0) ────────────────────────────────────────────────────
// A cookie-backed orientation: what the user is currently working toward.
// v0 is presentation-only - it orders and frames existing surfaces, it never
// computes anything. Graduates to the DB-backed Goals API (migration 021)
// without changing this shape; the server action then migrates the cookie.

export type GoalDirection = "increase" | "decrease" | "maintain";

export type FocusGoal = {
  title: string;
  direction: GoalDirection;
  metricIds: string[];
};

export const FOCUS_GOAL_COOKIE = "focus_goal";
const MAX_GOAL_METRICS = 4;
const MAX_GOAL_TITLE = 60;

export function parseFocusGoal(raw: string | undefined): FocusGoal | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return null;
    const title = typeof value.title === "string" ? value.title.slice(0, MAX_GOAL_TITLE) : "";
    const direction: GoalDirection =
      value.direction === "decrease" || value.direction === "maintain" ? value.direction : "increase";
    const metricIds = Array.isArray(value.metricIds)
      ? value.metricIds.filter((x: unknown): x is string => typeof x === "string").slice(0, MAX_GOAL_METRICS)
      : [];
    if (!title || metricIds.length === 0) return null;
    return { title, direction, metricIds };
  } catch {
    return null;
  }
}

export async function getFocusGoal(): Promise<FocusGoal | null> {
  const jar = await cookies();
  return parseFocusGoal(jar.get(FOCUS_GOAL_COOKIE)?.value);
}
