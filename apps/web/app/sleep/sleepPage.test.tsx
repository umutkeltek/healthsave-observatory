// /sleep end to end inside the web app: the real page and loaders against a
// stubbed backend. No module mocks (see year/yearPage.test.tsx).
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import type { SeriesPoint } from "../lib/api";
import { clearSwrCache } from "../lib/ttlCache";
import SleepPage from "./page";

const METRIC = { id: "sleep.stage", display_name: "Sleep", category: "sleep", value_type: "code", canonical_unit: null };

function stage(start: number, hours: number, code: string): SeriesPoint {
  return {
    t: new Date(start).toISOString(),
    interval_end: new Date(start + hours * 3_600_000).toISOString(),
    code,
    value: 1,
    unit: null,
    source_id: "apple",
    stream_id: null,
    confidence: null,
  };
}

function night(bedtime: number): SeriesPoint[] {
  return [stage(bedtime, 3, "core"), stage(bedtime + 3 * 3_600_000, 2, "deep"), stage(bedtime + 5 * 3_600_000, 2, "rem")];
}

const series = (range: string, points: SeriesPoint[]) => ({ metric: METRIC, range, start: "", end: "", points });

const realFetch = globalThis.fetch;
const realWarn = console.warn;
let answers: Record<string, () => Response> = {};

beforeEach(() => {
  clearSwrCache();
  console.warn = () => {};
  answers = {};
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const [range, answer] of Object.entries(answers)) {
      if (url.endsWith(`/sleep.stage/series?range=${range}`)) return answer();
    }
    return Response.json({ detail: "boom" }, { status: 500 });
  }) as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  console.warn = realWarn;
  clearSwrCache();
});

const render = async () => renderToStaticMarkup(await SleepPage());

describe("/sleep", () => {
  // The bug: a backend that did not answer was told to sync more data.
  test("a backend that does not answer is shown as unreachable, not as 'no sleep data yet'", async () => {
    const html = await render();
    expect(html).toContain("did not answer");
    expect(html).not.toContain("No sleep data yet");
  });

  test("an answered empty record still says there is no sleep data yet", async () => {
    answers = { "30d": () => Response.json(series("30d", [])), all: () => Response.json(series("all", [])) };
    expect(await render()).toContain("No sleep data yet");
  });

  // The bug: the all-time fallback's newest night, months old, was labelled
  // "Last night".
  test("an old night shown from the all-time fallback is not called last night", async () => {
    const old = Date.parse("2026-06-01T22:00:00Z");
    answers = { "30d": () => Response.json(series("30d", [])), all: () => Response.json(series("all", night(old))) };
    const html = await render();
    expect(html).not.toContain(">Last night<");
    expect(html).toContain("Latest night");
  });

  test("a night that ended this morning is still last night", async () => {
    const bedtime = Date.now() - 10 * 3_600_000;
    answers = { "30d": () => Response.json(series("30d", night(bedtime))) };
    expect(await render()).toContain(">Last night<");
  });
});
