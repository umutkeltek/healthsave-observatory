// The /year/[year] page and its card route, end to end inside the web app:
// real loaders and api client against a stubbed backend fetch. No module
// mocks (a process-wide mock.module leaked into other files in CI on 11-03).

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { clearSwrCache } from "../lib/ttlCache";
import { yearFixture } from "../lib/yearFixture";
import { GET as cardRoute } from "./[year]/card/route";
import YearPage from "./[year]/page";

const realFetch = globalThis.fetch;
let requested: string[] = [];

beforeEach(() => {
  clearSwrCache();
  requested = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    requested.push(url);
    if (url.endsWith("/api/v2/year/2025")) return Response.json(yearFixture());
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
    const html = await page("2025");
    expect(requested.some((url) => url.endsWith("/api/v2/year/2025"))).toBe(true);
    expect(html).toContain("2025, the year in your record");
    expect(html).toContain("9 days with nothing recorded: Aug 3 – Aug 11.");
    expect(html).toContain('src="/year/2025/card"');
  });

  test("opt-ins from the query string reach the card preview", async () => {
    const html = await page("2025", { numbers: "1", devices: "1" });
    expect(html).toContain('src="/year/2025/card?numbers=1&amp;devices=1"');
  });

  test("a failing backend shows the unreachable state", async () => {
    const html = await page("2024");
    expect(html).toContain("did not answer");
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
    const response = await card("2025");
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toContain("image/svg+xml");
    expect(response.headers.get("cache-control")).toContain("no-store");
    const svg = await response.text();
    const texts = [...svg.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => m[1]);
    for (const text of texts) expect(text.replaceAll("2025", "")).not.toMatch(/\d/);
    expect(svg).not.toContain("Apple Watch");
  });

  test("opted-in numbers appear; download sets a file name", async () => {
    const response = await card("2025", "?numbers=1&download=1");
    expect(await response.text()).toContain("days with data");
    expect(response.headers.get("content-disposition")).toBe('attachment; filename="year-in-health-2025.svg"');
  });

  test("unknown year is 404, unreachable backend is 502", async () => {
    expect((await card("1969")).status).toBe(404);
    expect((await card("2024")).status).toBe(502);
  });
});
