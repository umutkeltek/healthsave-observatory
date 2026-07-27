// Template data — kept separate from prefs.ts so client components can import
// these constants without pulling in next/headers.

export type TemplateId = "recovery" | "sleep" | "performance" | "minimal" | "full";

export type Template = {
  id: TemplateId;
  label: string;
  short: string;
  icon: string;
  sections: DashboardSectionKeys;
};

export type DashboardSectionKeys = {
  hero: boolean;
  goal: boolean;
  story: boolean;
  signals: boolean;
  vault: boolean;
  readiness: boolean;
  savedPanels: boolean;
};

export type DashboardSections = DashboardSectionKeys;

export const TEMPLATES: Template[] = [
  { id: "recovery", label: "Recovery First", short: "Hero, findings & readiness", icon: "💚",
    sections: { hero: true, goal: true, story: true, signals: false, vault: false, readiness: true, savedPanels: false } },
  { id: "sleep", label: "Sleep Deep", short: "Recovery score & sleep stages", icon: "🌙",
    sections: { hero: true, goal: true, story: false, signals: true, vault: false, readiness: false, savedPanels: false } },
  { id: "performance", label: "Performance", short: "Recovery, signals & strain", icon: "⚡",
    sections: { hero: true, goal: true, story: false, signals: true, vault: false, readiness: false, savedPanels: false } },
  { id: "minimal", label: "Minimal", short: "Just the recovery hero", icon: "◉",
    sections: { hero: true, goal: true, story: false, signals: false, vault: false, readiness: false, savedPanels: false } },
  { id: "full", label: "Full Observatory", short: "Every section visible", icon: "◆",
    sections: { hero: true, goal: true, story: true, signals: true, vault: true, readiness: true, savedPanels: true } },
];

export function defaultSections(): DashboardSections {
  return { hero: true, goal: true, story: true, signals: true, vault: true, readiness: true, savedPanels: true };
}
