// The change poll tells the browser when the page may be showing cached values
// that are being refreshed, so it can say "updating" and redraw when done.
import { afterEach, beforeEach, describe, expect, setSystemTime, test } from "bun:test";

import { liveAfterPoll, readCacheSignal } from "../../lib/liveSignal";
import { clearSwrCache, swrCache } from "../../lib/ttlCache";
import { GET } from "./route";

const T0 = new Date("2026-11-08T12:00:00Z").getTime();
const realFetch = globalThis.fetch;

beforeEach(() => {
  clearSwrCache();
  setSystemTime(T0);
  globalThis.fetch = (async () =>
    Response.json({ version_token: "t1" }, { headers: { etag: '"t1"' } })) as unknown as typeof fetch;
});

afterEach(() => {
  setSystemTime();
  globalThis.fetch = realFetch;
  clearSwrCache();
});

describe("/api/changes cache signal", () => {
  test("reports a stale value being refreshed, then when the refresh landed", async () => {
    await swrCache("readiness", 30_000, async () => "v1");
    setSystemTime(T0 + 60_000);
    let land: (value: string) => void = () => {};
    expect(await swrCache("readiness", 30_000, () => new Promise<string>((res) => (land = res)))).toBe("v1");

    const during = readCacheSignal((await GET(new Request("http://box/api/changes"))).headers);
    expect(during).toEqual({ refreshing: 1, settledAt: expect.any(Number) });

    land("v2");
    await new Promise((resolve) => setTimeout(resolve, 0));
    const after = readCacheSignal((await GET(new Request("http://box/api/changes"))).headers);
    expect(after).toEqual({ refreshing: 0, settledAt: T0 + 60_000 });
  });
});

describe("liveAfterPoll", () => {
  test("a refresh in flight shows updating and does not redraw yet", () => {
    expect(liveAfterPoll({ refreshing: 1, settledAt: 0 }, 100)).toEqual({ updating: true, redraw: false });
  });

  test("a refresh that landed after this page rendered redraws it", () => {
    expect(liveAfterPoll({ refreshing: 0, settledAt: 200 }, 100)).toEqual({ updating: false, redraw: true });
    expect(liveAfterPoll({ refreshing: 0, settledAt: 50 }, 100)).toEqual({ updating: false, redraw: false });
  });

  test("an older server without the signal changes nothing", () => {
    expect(liveAfterPoll(null, 100)).toEqual({ updating: false, redraw: false });
  });
});
