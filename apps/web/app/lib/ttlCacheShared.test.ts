// Next bundles route handlers (app/api/changes) separately from pages, so each
// bundle gets its own copy of this module. The cache must still be ONE cache:
// a clear from the change poll has to drop what the pages serve.
import { afterEach, describe, expect, test } from "bun:test";

import * as pages from "./ttlCache";

afterEach(() => pages.clearSwrCache());

describe("one cache across bundles", () => {
  test("a clear from another bundle's copy drops what this copy cached", async () => {
    // A query string makes Bun load a separate module instance, as a separate
    // Next bundle would.
    const changesRoute = (await import("./ttlCache.ts?bundle=route-handler")) as typeof pages;
    expect(changesRoute.swrCache).not.toBe(pages.swrCache);

    await pages.swrCache("readiness", 30_000, async () => "before sync");
    changesRoute.clearSwrCache();
    expect(await pages.swrCache("readiness", 30_000, async () => "after sync")).toBe("after sync");
  });

  test("a value cached through one copy is served through the other", async () => {
    const other = (await import("./ttlCache.ts?bundle=other")) as typeof pages;
    await other.swrCache("k", 30_000, async () => "v");
    expect(await pages.swrCache("k", 30_000, async () => "refetched")).toBe("v");
  });
});
