// The /year/[year] page and its card route, end to end inside the web app:
// real loaders and api client against a stubbed backend fetch. No module
// mocks (a process-wide mock.module leaked into other files in CI on 11-03).

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { clearSwrCache } from "../lib/ttlCache";
import { yearFixture } from "../lib/yearFixture";
import { GET as cardRoute } from "./[year]/card/route";
import YearPage from "./[year]/page";
import YearIndex from "./page";

// Relative to the real clock so the file keeps working next year: the stub
// backend says THIS year has not started (as it would for a person whose day
// is behind the server's), holds a year of data for LAST year, and fails for
// the year before.
const THIS = new Date().getUTCFullYear();
const LAST = THIS - 1;
const FAILING = THIS - 2;

const realFetch = globalThis.fetch;
let requested: string[] = [];

beforeEach(() => {
  clearSwrCache();
  requested = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);
    if (url.endsWith(`/api/v2/year/${LAST}`)) return Response.json(yearFixture());
    if (url.endsWith(`/api/v2/year/${THIS}`)) {
      return Response.json({ detail: `year_not_started: year ${THIS} has not started yet` }, { status: 422 });
    }
    return Response.json({ detail: "boom" }, { status: 500 });
  }) as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  clearSwrCache();
});

const page = async (year: string, search: Record<string, string> = {}) =>
  renderToStaticMarkup(await YearPage({ params: Promise.resolve({ year }), searchParams: Promise.resolve(search) }));

describe("/year/[year] page", () => {
  test("renders the year from the v2 year route", async () => {
    const html = await page(String(LAST));
    expect(requested.some((url) => url.endsWith(`/api/v2/year/${LAST}`))).toBe(true);
    expect(html).toContain(`${LAST}, the year in your record`);
    expect(html).toContain("9 days with nothing recorded: Aug 3 – Aug 11.");
    expect(html).toContain(`src="/year/${LAST}/card"`);
  });

  test("opt-ins from the query string reach the card preview", async () => {
    const html = await page(String(LAST), { numbers: "1", devices: "1" });
    expect(html).toContain(`src="/year/${LAST}/card?numbers=1&amp;devices=1"`);
  });

  test("a failing backend shows the unreachable state", async () => {
    const html = await page(String(FAILING));
    expect(html).toContain("did not answer");
  });

  test("a year the API says has not started shows that, not an outage", async () => {
    const html = await page(String(THIS));
    expect(html).toContain(`${THIS} has not started yet in your time zone.`);
  });

  test("/year falls back to the year before when this one has not started for the person", async () => {
    const html = renderToStaticMarkup(await YearIndex({ searchParams: Promise.resolve({}) }));
    expect(requested.some((url) => url.endsWith(`/api/v2/year/${THIS}`))).toBe(true);
    expect(html).toContain(`${LAST}, the year in your record`);
  });

  test("a year outside 1970..now is not found", async () => {
    await expect(page("1969")).rejects.toThrow();
    await expect(page("abcd")).rejects.toThrow();
    expect(requested).toEqual([]);
  });
});

describe("/year/[year]/card route", () => {
  const card = (year: string, query = "") =>
    cardRoute(new Request(`http://observatory.local/year/${year}/card${query}`), { params: Promise.resolve({ year }) });

  test("default card is an SVG with no personal numbers and no device names", async () => {
    const response = await card(String(LAST));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("image/svg+xml");
    expect(response.headers.get("cache-control")).toContain("no-store");
    const svg = await response.text();
    const texts = [...svg.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => m[1]);
    for (const text of texts) expect(text.replaceAll("2025", "")).not.toMatch(/\d/);
    expect(svg).not.toContain("Apple Watch");
  });

  test("opted-in numbers appear; download sets a file name", async () => {
    const response = await card(String(LAST), "?numbers=1&download=1");
    expect(await response.text()).toContain("days with data");
    expect(response.headers.get("content-disposition")).toBe(`attachment; filename="year-in-health-${LAST}.svg"`);
  });

  test("unknown or not-started year is 404, unreachable backend is 502", async () => {
    expect((await card("1969")).status).toBe(404);
    expect((await card(String(THIS))).status).toBe(404);
    expect((await card(String(FAILING))).status).toBe(502);
  });
});
