import { afterEach, beforeEach, describe, expect, setSystemTime, test } from "bun:test";

import { applyIntelligence, createMoment, postInsightsTrigger, postTestConnection, updateAnalyticalTime } from "./api";
import {
  clearSwrCache,
  expireSwrCache,
  FAILURE_BACKOFF_MS,
  MAX_STALE_MS,
  staleRefreshStatus,
  swrCache,
} from "./ttlCache";

const T0 = new Date("2026-11-08T12:00:00Z").getTime();
const TTL = 30_000;
const fail = () => Promise.reject(new Error("backend down"));
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

// A fetcher the test resolves by hand, counting how often it was called.
function controlled<T>() {
  let calls = 0;
  let resolve: (value: T) => void = () => {};
  let reject: (error: Error) => void = () => {};
  const fetcher = () => {
    calls += 1;
    return new Promise<T>((res, rej) => {
      resolve = res;
      reject = rej;
    });
  };
  return {
    fetcher,
    calls: () => calls,
    resolve: (value: T) => resolve(value),
    reject: (error: Error) => reject(error),
  };
}

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

  test("concurrent misses share one fetch", async () => {
    const backend = controlled<string>();
    const reads = [swrCache("k", TTL, backend.fetcher), swrCache("k", TTL, backend.fetcher)];
    backend.resolve("v1");
    expect(await Promise.all(reads)).toEqual(["v1", "v1"]);
    expect(backend.calls()).toBe(1);
  });

  // The review's regression: readiness older than 10x its TTL (5 minutes) was
  // refused and every view waited on a 5-20 s read.
  test("a stale value from a healthy backend is served at once, with one shared background refresh", async () => {
    await swrCache("readiness", TTL, async () => "v1");
    setSystemTime(T0 + 3 * 60 * 60_000);
    const backend = controlled<string>();
    expect(await swrCache("readiness", TTL, backend.fetcher)).toBe("v1");
    expect(await swrCache("readiness", TTL, backend.fetcher)).toBe("v1");
    expect(backend.calls()).toBe(1);
    expect(staleRefreshStatus().refreshing).toBe(1);

    backend.resolve("v2");
    await settle();
    expect(staleRefreshStatus()).toEqual({ refreshing: 0, settledAt: T0 + 3 * 60 * 60_000 });
    expect(await swrCache("readiness", TTL, fail)).toBe("v2");
  });

  test("past the max stale age the read waits for the backend", async () => {
    await swrCache("k", TTL, async () => "v1");
    setSystemTime(T0 + MAX_STALE_MS);
    expect(await swrCache("k", TTL, async () => "v2")).toBe("v2");
  });

  // Truthfulness: once the backend has failed, the old value is not shown
  // as current; the read fails (unreachable) instead.
  test("after a failed refresh the stale value is no longer served", async () => {
    await swrCache("k", TTL, async () => "v1");
    setSystemTime(T0 + TTL + 1);
    expect(await swrCache("k", TTL, fail)).toBe("v1");
    await settle();
    await expect(swrCache("k", TTL, async () => "v2")).rejects.toThrow("backend down");
  });

  // The review: after one failure every request started its own blocking fetch.
  test("within the backoff after a failure no request reaches the backend", async () => {
    await expect(swrCache("k", TTL, fail)).rejects.toThrow("backend down");
    let calls = 0;
    const counting = async () => {
      calls += 1;
      return "v";
    };
    setSystemTime(T0 + FAILURE_BACKOFF_MS - 1);
    await expect(swrCache("k", TTL, counting)).rejects.toThrow("backend down");
    await expect(swrCache("k", TTL, counting)).rejects.toThrow("backend down");
    expect(calls).toBe(0);
  });

  test("after the backoff one blocking attempt is shared by concurrent callers", async () => {
    await expect(swrCache("k", TTL, fail)).rejects.toThrow("backend down");
    setSystemTime(T0 + FAILURE_BACKOFF_MS);
    const backend = controlled<string>();
    const reads = [swrCache("k", TTL, backend.fetcher), swrCache("k", TTL, backend.fetcher)];
    backend.resolve("back");
    expect(await Promise.all(reads)).toEqual(["back", "back"]);
    expect(backend.calls()).toBe(1);
  });

  test("a value fetched before a clear is not put back", async () => {
    const backend = controlled<string>();
    const read = swrCache("k", TTL, backend.fetcher);
    clearSwrCache();
    backend.resolve("old");
    expect(await read).toBe("old");
    expect(await swrCache("k", TTL, async () => "new")).toBe("new");
  });
});

describe("expireSwrCache", () => {
  test("a fresh value becomes stale: served at once, refreshed once in the background", async () => {
    await swrCache("k", TTL, async () => "v1");
    expireSwrCache();
    const backend = controlled<string>();
    expect(await swrCache("k", TTL, backend.fetcher)).toBe("v1");
    expect(backend.calls()).toBe(1);
    backend.resolve("v2");
    await settle();
    expect(await swrCache("k", TTL, fail)).toBe("v2");
  });

  test("a fetch that started before an expire lands already stale", async () => {
    const backend = controlled<string>();
    const read = swrCache("k", TTL, backend.fetcher);
    expireSwrCache();
    backend.resolve("before the change");
    expect(await read).toBe("before the change");
    const next = controlled<string>();
    expect(await swrCache("k", TTL, next.fetcher)).toBe("before the change");
    expect(next.calls()).toBe(1);    next.resolve("after");
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

  // The review: every successful write cleared every key, including the
  // read-only connection test and the POSTs behind "Refresh brief".
  test("a write drops only what it changes", async () => {
    globalThis.fetch = (async () => Response.json({ ok: true, status: "completed" })) as unknown as typeof fetch;
    const keep = async () => {
      expect(await swrCache("readiness", TTL, async () => "refetched")).toBe("cached");
      expect(await swrCache("series:vital.heart_rate:7d", TTL, async () => "refetched")).toBe("cached");
    };
    await swrCache("readiness", TTL, async () => "cached");
    await swrCache("series:vital.heart_rate:7d", TTL, async () => "cached");
    await swrCache("moments@owner:abc", TTL, async () => "cached");
    await swrCache("receipts", TTL, async () => "cached");

    await postTestConnection({ provider: "ollama", model: "m" });
    await postInsightsTrigger("weekly_summary");
    await keep();

    await createMoment({ kind: "custom", title: "t", start_at: new Date(T0).toISOString() });
    await keep();
    expect(await swrCache("moments@owner:abc", TTL, async () => "after")).toBe("after");

    await applyIntelligence({ mode: "off" });
    await keep();
    expect(await swrCache("receipts", TTL, async () => "after")).toBe("after");
  });
});
