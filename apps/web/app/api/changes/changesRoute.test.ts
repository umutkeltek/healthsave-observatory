// The change poll tells the browser when the page may be showing cached values
// that are being refreshed, so it can say "updating" and redraw when done.
import { afterEach, beforeEach, describe, expect, setSystemTime, test } from "bun:test";

import { liveAfterPoll, readCacheSignal } from "../../lib/liveSignal";
import { fakeClocks } from "../../lib/testClock";
import { clearSwrCache, swrCache } from "../../lib/ttlCache";
import { GET } from "./route";

const T0 = new Date("2026-11-08T12:00:00Z").getTime();
const realFetch = globalThis.fetch;

let clocks: ReturnType<typeof fakeClocks>;

beforeEach(() => {
  clearSwrCache();
  clocks = fakeClocks(T0, setSystemTime);
  globalThis.fetch = (async () =>
    Response.json({ version_token: "t1" }, { headers: { etag: '"t1"' } })) as unknown as typeof fetch;
});

afterEach(() => {
  clocks.restore();
  globalThis.fetch = realFetch;
  clearSwrCache();
});

describe("/api/changes cache signal", () => {
  test("reports a stale value being refreshed, then when the refresh landed", async () => {
    await swrCache("readiness", 30_000, async () => "v1");
    clocks.at(60_000);
    let land: (value: string) => void = () => {};
    expect(await swrCache("readiness", 30_000, () => new Promise<string>((res) => (land = res)))).toBe("v1");

    const during = readCacheSignal((await GET(new Request("http://box/api/changes"))).headers);
    expect(during?.refreshing).toBe(1);

    land("v2");
    await new Promise((resolve) => setTimeout(resolve, 0));
    const after = readCacheSignal((await GET(new Request("http://box/api/changes"))).headers);
    // Counted, not timed: a wall-clock step cannot hide that it landed.
    expect(after).toEqual({ refreshing: 0, settled: (during?.settled ?? 0) + 1 });
  });
});

describe("liveAfterPoll", () => {
  test("a refresh in flight shows updating and does not redraw yet", () => {
    expect(liveAfterPoll({ refreshing: 1, settled: 0 }, 0)).toEqual({ updating: true, redraw: false });
  });

  test("a refresh that landed after this page rendered redraws it", () => {
    expect(liveAfterPoll({ refreshing: 0, settled: 3 }, 2)).toEqual({ updating: false, redraw: true });
    expect(liveAfterPoll({ refreshing: 0, settled: 2 }, 2)).toEqual({ updating: false, redraw: false });
  });

  test("an older server without the signal changes nothing", () => {
    expect(liveAfterPoll(null, 100)).toEqual({ updating: false, redraw: false });
  });
});

// The re-review: every poll that saw a new fingerprint deleted the whole read
// cache. During a sync that happens poll after poll: the instant stale path
// never ran, and each delete let the next caller start another fetch for a
// key already being fetched.
describe("a fingerprint move expires the cache instead of deleting it", () => {
  let tag = 0;
  const poll = async () => {
    const sent = `"t${tag}"`;
    tag += 1;
    const answer = `"t${tag}"`;
    globalThis.fetch = (async () =>
      Response.json({ version_token: answer }, { headers: { etag: answer } })) as unknown as typeof fetch;
    await GET(new Request("http://box/api/changes", { headers: { "if-none-match": sent } }));
  };
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

  function controlled() {
    let calls = 0;
    let resolve: (value: string) => void = () => {};
    return {
      fetcher: () => {
        calls += 1;
        return new Promise<string>((res) => (resolve = res));
      },
      calls: () => calls,
      resolve: (value: string) => resolve(value),
    };
  }

  test("after new data the cached value is served at once while one refresh runs", async () => {
    await swrCache("readiness", 30_000, async () => "v1");
    await poll();
    const backend = controlled();
    const read = swrCache("readiness", 30_000, backend.fetcher);
    expect(await Promise.race([read, settle().then(() => "still waiting")])).toBe("v1");
    expect(backend.calls()).toBe(1);
    const signal = readCacheSignal((await GET(new Request("http://box/api/changes"))).headers);
    expect(signal?.refreshing).toBe(1);
    backend.resolve("v2");
  });

  test("a fetch in flight stays shared across fingerprint moves", async () => {
    const backend = controlled();
    const reads = [swrCache("readiness", 30_000, backend.fetcher)];
    for (let i = 0; i < 3; i++) {
      await poll();
      reads.push(swrCache("readiness", 30_000, backend.fetcher));
    }
    expect(backend.calls()).toBe(1);
    backend.resolve("v1");
    expect(await Promise.all(reads)).toEqual(["v1", "v1", "v1", "v1"]);
  });
});
