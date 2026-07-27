// Cookie-backed user preferences, read server-side so every page renders the
// right mode with zero hydration flash. Written only by the server actions in
// actions.ts.

import { cookies } from "next/headers";
import { defaultSections, TEMPLATES } from "./templates";
import type { DashboardSections, DashboardSectionKeys, Template, TemplateId } from "./templates";

export type Density = "essentials" | "observatory";

export const DENSITY_COOKIE = "density";
export const PINNED_COOKIE = "pinned_metrics";
export const MAX_PINS = 16;

// ── Dashboard Templates ──────────────────────────────────────────────────
// Template definitions live in lib/templates.ts (no server imports) so client
// components can import them. This file re-exports + adds cookie persistence.

export type { DashboardSections, DashboardSectionKeys, Template, TemplateId };
export { TEMPLATES, defaultSections };

export const DASHBOARD_COOKIE = "dashboard_sections";

export function parseSections(raw: string | undefined): DashboardSections {
  if (!raw) return defaultSections();
  try {
    const obj = JSON.parse(raw);
    if (typeof obj !== "object" || obj === null) return defaultSections();
    return {
      hero: obj.hero === true,
      goal: obj.goal === true,
      story: obj.story === true,
      signals: obj.signals === true,
      vault: obj.vault === true,
      readiness: obj.readiness === true,
      // Added after the original dashboard cookie shipped. Missing means the
      // user has an older cookie and should inherit the new default, not have a
      // successfully saved Explore panel remain invisibly disabled.
      savedPanels: obj.savedPanels !== false,
    };
  } catch {
    return defaultSections();
  }
}

export async function getDashboardSections(): Promise<DashboardSections> {
  const jar = await cookies();
  return parseSections(jar.get(DASHBOARD_COOKIE)?.value);
}

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

// ── Saved Explore panels → Today bridge ──────────────────────────────────
// Users can save an Explore dashboard view and have it appear as a compact
// card on Today. Stored as a cookie (server-readable, no client hydration).

export type SavedPanel = {
  id: string;
  label: string;
  state: string; // serialized ExploreState (URL query string via explore.ts)
};

export const SAVED_PANELS_COOKIE = "saved_panels";
export const MAX_SAVED_PANELS = 8;
export const MAX_SAVED_PANEL_LABEL = 60;
export const MAX_SAVED_PANEL_STATE = 1200;
// Leave headroom for the cookie name + attributes and browser implementation
// differences under the common 4096-byte per-cookie ceiling.
export const MAX_SAVED_PANELS_COOKIE_BYTES = 3500;

function validSavedPanel(value: unknown): value is SavedPanel {
  if (typeof value !== "object" || value === null) return false;
  const panel = value as Partial<SavedPanel>;
  return (
    typeof panel.id === "string" &&
    panel.id.length > 0 &&
    panel.id.length <= 80 &&
    typeof panel.label === "string" &&
    panel.label.trim().length > 0 &&
    panel.label.length <= MAX_SAVED_PANEL_LABEL &&
    typeof panel.state === "string" &&
    panel.state.length > 0 &&
    panel.state.length <= MAX_SAVED_PANEL_STATE
  );
}

export function parseSavedPanels(raw: string | undefined): SavedPanel[] {
  if (!raw) return [];
  try {
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter(validSavedPanel).slice(-MAX_SAVED_PANELS) : [];
  } catch {
    return [];
  }
}

export function appendSavedPanel(panels: SavedPanel[], panel: SavedPanel): SavedPanel[] {
  const candidates = [...panels.filter((saved) => saved.label !== panel.label), panel].slice(
    -MAX_SAVED_PANELS,
  );
  while (
    candidates.length > 1 &&
    encodeURIComponent(JSON.stringify(candidates)).length > MAX_SAVED_PANELS_COOKIE_BYTES
  ) {
    candidates.shift();
  }
  return candidates;
}

export async function getSavedPanels(): Promise<SavedPanel[]> {
  const jar = await cookies();
  return parseSavedPanels(jar.get(SAVED_PANELS_COOKIE)?.value);
}
