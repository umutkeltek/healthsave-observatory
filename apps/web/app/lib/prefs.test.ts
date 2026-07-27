import { describe, expect, test } from "bun:test";
import { appendSavedPanel, MAX_SAVED_PANELS, parseSavedPanels, parseSections } from "./prefs";

describe("dashboard section cookie migration", () => {
  test("enables saved panels when reading a cookie written before that section existed", () => {
    const sections = parseSections(
      JSON.stringify({ hero: true, goal: true, story: true, signals: true, vault: true, readiness: true }),
    );
    expect(sections.savedPanels).toBe(true);
  });

  test("preserves an explicit saved-panel opt-out", () => {
    const sections = parseSections(JSON.stringify({ hero: true, savedPanels: false }));
    expect(sections.savedPanels).toBe(false);
  });
});

describe("saved panel persistence", () => {
  test("keeps the newest panel when the limit is exceeded", () => {
    const existing = Array.from({ length: MAX_SAVED_PANELS }, (_, index) => ({
      id: `p${index}`,
      label: `Panel ${index}`,
      state: "range=30d&panels=line%3Am",
    }));
    const next = appendSavedPanel(existing, {
      id: "new",
      label: "Newest",
      state: "range=7d&panels=line%3An",
    });
    expect(next).toHaveLength(MAX_SAVED_PANELS);
    expect(next.at(-1)?.id).toBe("new");
    expect(next.some((panel) => panel.id === "p0")).toBe(false);
  });

  test("drops oldest panels until the encoded cookie fits", () => {
    const large = Array.from({ length: MAX_SAVED_PANELS }, (_, index) => ({
      id: `p${index}`,
      label: `Panel ${index}`,
      state: `range=all&panels=${"vital.hrv_sdnn,".repeat(60)}${index}`,
    }));
    const next = appendSavedPanel(large.slice(0, -1), large.at(-1)!);
    expect(encodeURIComponent(JSON.stringify(next)).length).toBeLessThanOrEqual(3500);
    expect(next.at(-1)?.id).toBe(`p${MAX_SAVED_PANELS - 1}`);
  });

  test("rejects malformed and oversized cookie records", () => {
    const parsed = parseSavedPanels(
      JSON.stringify([
        { id: "ok", label: "Valid", state: "range=7d&panels=line%3Am" },
        { id: "", label: "Missing id", state: "x" },
        { id: "huge", label: "Huge", state: "x".repeat(5000) },
      ]),
    );
    expect(parsed.map((panel) => panel.id)).toEqual(["ok"]);
  });
});
