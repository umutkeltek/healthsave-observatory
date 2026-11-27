// The read cache must not grow without limit: failed reads stay as entries,
// and /library/<id> and /compare?metric=<id> key on ids taken from the URL.
import { afterEach, beforeEach, describe, expect, setSystemTime, test } from "bun:test";

import { fakeClocks } from "./testClock";
import { clearSwrCache, swrCache } from "./ttlCache";

const T0 = new Date("2026-11-08T12:00:00Z").getTime();
const TTL = 30_000;
const CAP = 500;

function keys(): string[] {
  const state = (globalThis as Record<symbol, { entries: Map<string, unknown> }>)[Symbol.for("healthsave.web.swrCache")];
  return [...state.entries.keys()];
}

let clocks: ReturnType<typeof fakeClocks>;

beforeEach(() => {
  clearSwrCache();
  clocks = fakeClocks(T0, setSystemTime);
});

afterEach(() => {
  clocks.restore();
  clearSwrCache();
});

describe("bounded read cache", () => {
  test(`at most ${CAP} keys, the least recently used evicted first`, async () => {
    await swrCache("pinned", TTL, async () => "kept");
    for (let i = 0; i < CAP + 100; i++) {
      await swrCache(`series:custom.metric_${i}:30d`, TTL, async () => i);
      if (i % 50 === 0) await swrCache("pinned", TTL, async () => "refetched");
    }
    expect(keys().length).toBeLessThanOrEqual(CAP);
    expect(keys()).toContain("pinned");
    expect(keys()).not.toContain("series:custom.metric_0:30d");
    expect(await swrCache("pinned", TTL, async () => "refetched")).toBe("kept");
  });

  test("a failed read is evicted once its backoff has passed", async () => {
    await expect(swrCache("series:typo.metric:30d", TTL, () => Promise.reject(new Error("404")))).rejects.toThrow();
    expect(keys()).toContain("series:typo.metric:30d");
    clocks.at(60_000);
    await swrCache("readiness", TTL, async () => "v");
    expect(keys()).not.toContain("series:typo.metric:30d");
  });
});
