// The app's pages, in sidebar order. The sidebar and the ⌘K search both read
// this list, so a new page shows up in both or in neither.
//
// The three-pillar structure mirrors Whoop's Strain / Recovery / Sleep:
//   Today = Recovery (the hero instrument)
//   Sleep = Sleep quality, stages, consistency, debt
//   Activity = Strain (cardio load, steps, exercise)
export type NavGroup = "essentials" | "explore" | "manage";
export type NavKey =
  | "today"
  | "sleep"
  | "activity"
  | "labs"
  | "genetics"
  | "year"
  | "findings"
  | "data"
  | "sources"
  | "privacy"
  | "explore"
  | "library"
  | "compare"
  | "relationships"
  | "experiments"
  | "timeline"
  | "integrations"
  | "intelligence"
  | "settings";
export type NavItem = { href: string; labelKey: NavKey; icon: string; group: NavGroup };

export const NAV: readonly NavItem[] = [
  { href: "/", labelKey: "today", icon: "overview", group: "essentials" },
  { href: "/sleep", labelKey: "sleep", icon: "sleep", group: "essentials" },
  { href: "/activity", labelKey: "activity", icon: "activity", group: "essentials" },
  { href: "/labs", labelKey: "labs", icon: "labs", group: "essentials" },
  { href: "/findings", labelKey: "findings", icon: "findings", group: "essentials" },
  { href: "/data", labelKey: "data", icon: "data", group: "essentials" },
  { href: "/sources", labelKey: "sources", icon: "sources", group: "essentials" },
  { href: "/privacy", labelKey: "privacy", icon: "privacy", group: "essentials" },
  { href: "/explore", labelKey: "explore", icon: "explore", group: "explore" },
  { href: "/genetics", labelKey: "genetics", icon: "relationships", group: "explore" },
  { href: "/library", labelKey: "library", icon: "library", group: "explore" },
  { href: "/compare", labelKey: "compare", icon: "compare", group: "explore" },
  { href: "/relationships", labelKey: "relationships", icon: "relationships", group: "explore" },
  { href: "/experiments", labelKey: "experiments", icon: "experiments", group: "explore" },
  { href: "/timeline", labelKey: "timeline", icon: "findings", group: "explore" },
  { href: "/year", labelKey: "year", icon: "year", group: "explore" },
  { href: "/integrations", labelKey: "integrations", icon: "integrations", group: "manage" },
  { href: "/intelligence", labelKey: "intelligence", icon: "intelligence", group: "manage" },
  { href: "/settings", labelKey: "settings", icon: "settings", group: "manage" },
];
