// The bug (audit web #19): cookie-backed preferences dropped things without a
// word. A 17th pin answered "ok" and pinned nothing; saving a ninth Explore view
// to Today pushed the oldest off Today and said only "Saved!".
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { togglePinAction } from "./actions";
import { inRequest } from "./testRequest";
import { evictedPanels, MAX_PINS, MAX_SAVED_PANELS, PINNED_COOKIE, appendSavedPanel } from "./prefs";
import { resetWebAuthStoreForTests } from "./webAuthStore.server";

const saved = { password: process.env.WEB_PASSWORD, file: process.env.WEB_AUTH_FILE };
let dir = "";

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "hs-prefs-"));
  process.env.WEB_AUTH_FILE = join(dir, "web-auth.json");
  delete process.env.WEB_PASSWORD;
});

afterEach(async () => {
  await resetWebAuthStoreForTests();
  rmSync(dir, { recursive: true, force: true });
  for (const [key, value] of [
    ["WEB_PASSWORD", saved.password],
    ["WEB_AUTH_FILE", saved.file],
  ] as const) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
});

describe("pin limit", () => {
  test("a pin past the limit is refused with the reason, not answered ok", async () => {
    const full = Array.from({ length: MAX_PINS }, (_, i) => `vital.metric_${i}`);
    const cookie = `${PINNED_COOKIE}=${encodeURIComponent(JSON.stringify(full))}`;
    const result = await inRequest(cookie, () => togglePinAction("vital.one_more"));
    expect(result.ok).toBe(false);
    expect(result.error).toBe(`You can pin up to ${MAX_PINS} signals. Unpin one first.`);
  });
});

describe("saved views on Today", () => {
  const panel = (i: number) => ({ id: `p${i}`, label: `Panel ${i}`, state: "range=30d&panels=line%3Avital.hrv_sdnn" });

  test("the views a save pushed off Today are named", () => {
    const existing = Array.from({ length: MAX_SAVED_PANELS }, (_, i) => panel(i));
    const added = { id: "new", label: "Newest", state: "range=7d&panels=line%3Avital.hrv_sdnn" };
    const next = appendSavedPanel(existing, added);
    expect(evictedPanels(existing, next, added).map((p) => p.label)).toEqual(["Panel 0"]);
  });

  test("replacing a view by its own label removes nothing else", () => {
    const existing = [panel(0), panel(1)];
    const again = { id: "p1b", label: "Panel 1", state: "range=7d&panels=line%3Avital.hrv_sdnn" };
    expect(evictedPanels(existing, appendSavedPanel(existing, again), again)).toEqual([]);
  });
});
