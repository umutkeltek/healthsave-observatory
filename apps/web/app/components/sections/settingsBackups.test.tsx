// The Settings backup card: the free way comes first and is complete, and the
// one Care line is a plain link that loads nothing until someone clicks it.
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { BackupsSection, CARE_URL } from "./SettingsSections";

const out = renderToStaticMarkup(<BackupsSection />);

describe("Settings backup card", () => {
  test("names the free backup and restore commands before Care", () => {
    const backup = out.indexOf("healthsave backup");
    const restore = out.indexOf("healthsave restore FILE");
    const care = out.indexOf("Observatory Care");
    expect(backup).toBeGreaterThan(-1);
    expect(restore).toBeGreaterThan(-1);
    expect(out).toContain("Both are free.");
    expect(care).toBeGreaterThan(Math.max(backup, restore));
  });

  test("Care is one link to the pricing page, tagged with where it came from", () => {
    const links = [...out.matchAll(/<a [^>]*>/g)].map((m) => m[0]);
    expect(links).toHaveLength(1);
    expect(links[0]).toContain(`href="${CARE_URL}"`);
    expect(new URL(CARE_URL).hostname).toBe("healthsave.app");
    expect(new URL(CARE_URL).searchParams.get("utm_source")).toBe("observatory_app");
  });

  test("the link sends no referrer and nothing loads from outside", () => {
    expect(out).toContain('rel="noreferrer"');
    expect(out).not.toMatch(/<(script|img|iframe|link)\b/);
  });
});
