import { describe, expect, test } from "bun:test";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { dictionaries, LOCALES } from "./i18n";
import { NAV } from "./nav";

const APP = join(import.meta.dir, "..");

// Top-level folders under app/ that are pages a person navigates to.
function pageRoutes(): string[] {
  return readdirSync(APP, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && existsSync(join(APP, entry.name, "page.tsx")))
    .map((entry) => `/${entry.name}`);
}

// Pages reachable by URL that deliberately stay out of the nav.
const NOT_IN_NAV = new Set(["/demo", "/login", "/auth"]);

describe("navigation list", () => {
  test("every top-level page is in the nav, so the sidebar and search both reach it", () => {
    const inNav = new Set(NAV.map((item) => item.href));
    const missing = pageRoutes().filter((route) => !NOT_IN_NAV.has(route) && !inNav.has(route));
    expect(missing).toEqual([]);
  });

  test("every nav entry points at a page that exists", () => {
    for (const item of NAV) {
      const file = item.href === "/" ? join(APP, "page.tsx") : join(APP, item.href.slice(1), "page.tsx");
      expect(existsSync(file)).toBe(true);
    }
  });

  test("every nav entry has a name in every language", () => {
    for (const locale of LOCALES) {
      for (const item of NAV) {
        expect(dictionaries[locale].nav[item.labelKey]?.trim().length ?? 0).toBeGreaterThan(0);
      }
    }
  });

  test("the search box builds its page list from the nav, not from its own copy", () => {
    const source = readFileSync(join(APP, "components", "CommandPalette.tsx"), "utf8");
    expect(source).toContain('from "../lib/nav"');
    expect(source).not.toMatch(/href:\s*"\/(sleep|labs|year|settings)"/);
  });
});
