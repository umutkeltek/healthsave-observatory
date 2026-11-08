import { afterEach, beforeEach, describe, expect, setSystemTime, test } from "bun:test";

import { createMoment, updateAnalyticalTime } from "./api";
import { clearSwrCache, swrCache } from "./ttlCache";

const T0 = new Date("2026-11-08T12:00:00Z").getTime();
const TTL = 30_000;
const fail = () => Promise.reject(new Error("backend down"));
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

const realFetch = globalThis.fetch;

beforeEach(() => {
  clearSwrCache();
  setSystemTime(T0);
});

afterEach(() => {
  setSystemTime();
  globalThis.fetch = realFetch;
  clearSwrCache();
});

describe("swrCache", () => {
  test("a fresh hit is served without a fetch", async () => {
    await swrCache("k", TTL, async () => "v1");
    setSystemTime(T0 + TTL - 1);
    expect(await swrCache("k", TTL, fail)).toBe("v1");
  });

  test("a stale hit is served once while it refreshes in the background", async () => {
    await swrCache("k", TTL, async () => "v1");
    setSystemTime(T0 + TTL + 1);
    expect(await swrCache("k", TTL, async () => "v2")).toBe("v1");
    await settle();
    expect(await swrCache("k", TTL, fail)).toBe("v2");
  });

  // The bug: with the backend down, every refresh failed and the cache kept
  // serving the old value as if it were current, forever.
  test("after a failed refresh the next read waits for the backend instead of serving stale data", async () => {
    await swrCache("k", TTL, async () => "v1");
    setSystemTime(T0 + TTL + 1);
    expect(await swrCache("k", TTL, fail)).toBe("v1");
    await settle();
    await expect(swrCache("k", TTL, fail)).rejects.toThrow("backend down");
  });

  test("a value past its max age is never served, even before any refresh failed", async () => {
    await swrCache("k", TTL, async () => "v1");
    setSystemTime(T0 + 60 * 60_000);
    await expect(swrCache("k", TTL, fail)).rejects.toThrow("backend down");
  });
});

describe("writes invalidate cached reads", () => {
  test("a successful write drops cached reads, so the page shows what was just saved", async () => {
    globalThis.fetch = (async () => Response.json({ id: 1 })) as unknown as typeof fetch;
    await swrCache("moments", TTL, async () => "before");
    await createMoment({ kind: "custom", title: "t", start_at: new Date(T0).toISOString() });
    expect(await swrCache("moments", TTL, async () => "after")).toBe("after");

    await swrCache("analytical-time", TTL, async () => "before");
    await updateAnalyticalTime({ time_zone: "UTC", day_boundary_minutes: 0 });
    expect(await swrCache("analytical-time", TTL, async () => "after")).toBe("after");
  });

  test("a failed write keeps the cache", async () => {
    globalThis.fetch = (async () => Response.json({ detail: "no" }, { status: 422 })) as unknown as typeof fetch;
    await swrCache("moments", TTL, async () => "before");
    await expect(createMoment({ kind: "custom", title: "t", start_at: "x" })).rejects.toThrow();
    expect(await swrCache("moments", TTL, fail)).toBe("before");
  });
});
