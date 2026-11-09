// The change poll tells the browser when the page may be showing cached values
// that are being refreshed, so it can say "updating" and redraw when done.
import { afterEach, beforeEach, describe, expect, setSystemTime, test } from "bun:test";

import {
  afterPoll,
  armWatch,
  liveAfterPoll,
  nextPollDelay,
  NAV_WATCH_MS,
  POLL_MS,
  readCacheSignal,
  UPDATING_POLL_MS,
} from "../../lib/liveSignal";
import { fakeClocks } from "../../lib/testClock";
import { clearSwrCache, inRenderScopeForTests, renderedSettledMark, staleRefreshStatus, swrCache } from "../../lib/ttlCache";
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

describe("the page's render mark", () => {
  // The bug: the root layout read the landed-refresh count while the page's
  // own reads ran in parallel. A stale value the page showed, refreshed fast
  // enough to land before the layout read the count, counted as already shown:
  // the poll never redrew and the page kept the old value.
  test("a refresh this render started is never counted as shown, even if it lands first", async () => {
    await swrCache("readiness", 30_000, async () => "v1");
    clocks.at(60_000);
    await inRenderScopeForTests(async () => {
      // The page's read: the stale value at once, a background refresh starts.
      expect(await swrCache("readiness", 30_000, async () => "v2")).toBe("v1");
      await new Promise((resolve) => setTimeout(resolve, 0)); // the refresh lands
      // Only now does the layout ask for the mark.
      const signal = staleRefreshStatus();
      expect(signal.refreshing).toBe(0);
      expect(liveAfterPoll(signal, renderedSettledMark()).redraw).toBe(true);
      // What the layout used to pass: it hid the landed refresh.
      expect(liveAfterPoll(signal, signal.settled).redraw).toBe(false);
    });
  });

  // Fails if the mark is read live instead of once per render: a refresh
  // landing mid-render moves the live count but not this render's mark.
  test("one render has one mark, taken before its first read", async () => {
    await swrCache("a", 30_000, async () => 1);
    clocks.at(60_000);
    await inRenderScopeForTests(async () => {
      const first = renderedSettledMark();
      expect(await swrCache("a", 30_000, async () => 2)).toBe(1); // stale: refresh starts
      await new Promise((resolve) => setTimeout(resolve, 0)); // and lands
      expect(staleRefreshStatus().settled).toBe(first + 1);
      expect(renderedSettledMark()).toBe(first);
    });
  });

  test("a new render takes a new mark", async () => {
    await swrCache("a", 30_000, async () => 1);
    clocks.at(60_000);
    const first = await inRenderScopeForTests(async () => {
      const mark = renderedSettledMark();
      await swrCache("a", 30_000, async () => 2);
      await new Promise((resolve) => setTimeout(resolve, 0));
      return mark;
    });
    expect(await inRenderScopeForTests(async () => renderedSettledMark())).toBe(first + 1);
  });
});

describe("when the live pill polls", () => {
  const base = { hidden: false, updating: false, now: 100_000, watchUntil: 0 };

  test("a hidden tab does not poll at all", () => {
    expect(nextPollDelay({ ...base, hidden: true })).toBeNull();
    expect(nextPollDelay({ ...base, hidden: true, updating: true })).toBeNull();
  });

  test("a settled, visible tab polls at the slow cadence", () => {
    expect(nextPollDelay(base)).toBe(POLL_MS);
  });

  // The bug: the poll ran on a fixed 30 s timer, so after a soft navigation
  // that showed cached values the pill said "live" and the redraw came up to
  // 30 s late.
  test("right after a navigation it polls at the fast cadence for a while", () => {
    const watchUntil = base.now + NAV_WATCH_MS;
    expect(nextPollDelay({ ...base, watchUntil })).toBe(UPDATING_POLL_MS);
    expect(nextPollDelay({ ...base, watchUntil, now: watchUntil + 1 })).toBe(POLL_MS);
  });

  test("while cached values are being refreshed it polls fast", () => {
    expect(nextPollDelay({ ...base, updating: true })).toBe(UPDATING_POLL_MS);
  });
});

// The bug (review of the navigation fix): every redraw re-armed the 10 s fast
// window, and every new change token causes a redraw, so while data arrived
// faster than every 10 s (a backfill, connectors) a visible tab polled and
// redrew every 2 s for as long as it lasted, instead of every 30 s.
describe("the live poll over time", () => {
  test("only a navigation arms fast polling; redraws caused by new data do not", () => {
    let memory = armWatch({ etag: '"t0"', wasLive: true, renderedSettled: 0, watchUntil: 0 }, 0);
    let now = 0;
    let token = 0;
    const delays: { at: number; delay: number }[] = [];
    while (now < 120_000) {
      // New data on the backend every time it is asked.
      token += 1;
      const step = afterPoll(memory, { status: 200, etag: `"t${token}"`, signal: { refreshing: 0, settled: 0 } }, now, false);
      expect(step.refresh).toBe(true);
      memory = step.memory;
      delays.push({ at: now, delay: step.delay ?? -1 });
      now += step.delay ?? POLL_MS;
    }
    const inWindow = delays.filter((d) => d.at < NAV_WATCH_MS);
    const after = delays.filter((d) => d.at >= NAV_WATCH_MS);
    expect(inWindow.every((d) => d.delay === UPDATING_POLL_MS)).toBe(true);
    expect(after.length).toBeGreaterThan(0);
    expect(after.every((d) => d.delay === POLL_MS)).toBe(true);
  });

  test("a redraw after a cached value was refreshed does not re-arm it either", () => {
    let memory = { etag: '"t0"', wasLive: true, renderedSettled: 0, watchUntil: 0 };
    const step = afterPoll(memory, { status: 304, etag: '"t0"', signal: { refreshing: 0, settled: 1 } }, 50_000, false);
    expect(step.refresh).toBe(true);
    expect(step.delay).toBe(POLL_MS);
    memory = step.memory;
    expect(memory.renderedSettled).toBe(1);
  });

  test("a hidden tab schedules nothing, whatever the answer", () => {
    const memory = armWatch({ etag: null, wasLive: false, renderedSettled: 0, watchUntil: 0 }, 0);
    expect(afterPoll(memory, { status: 200, etag: '"t1"', signal: null }, 1, true).delay).toBeNull();
  });
});
