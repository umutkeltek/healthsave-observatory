// /library/[metricId] against a stubbed backend, inside a request scope (the
// page reads the pinned-signals cookie). No module mocks.
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { inRequest } from "../../lib/testRequest";
import { clearSwrCache } from "../../lib/ttlCache";
import MetricDetailPage from "./page";

const realFetch = globalThis.fetch;
const realWarn = console.warn;
let catalogUp = false;

beforeEach(() => {
  clearSwrCache();
  catalogUp = false;
  console.warn = () => {};
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input);
    if (catalogUp && url.endsWith("/api/v2/metrics")) {
      return Response.json([{ id: "vital.heart_rate", display_name: "Heart Rate", category: "vital", value_type: "numeric", canonical_unit: "bpm" }]);
    }
    if (catalogUp && url.includes("/api/v2/metrics/vital.unknown_thing/series")) {
      return Response.json({ detail: "unknown metric" }, { status: 404 });
    }
    return Response.json({ detail: "boom" }, { status: 500 });
  }) as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  console.warn = realWarn;
  clearSwrCache();
});

const render = (metricId: string) =>
  inRequest("", async () =>
    renderToStaticMarkup(
      await MetricDetailPage({ params: Promise.resolve({ metricId }), searchParams: Promise.resolve({ range: "30d" }) }),
    ),
  );

describe("/library/[metricId]", () => {
  // The bug: with the backend down the catalog read failed too, and the page
  // said the signal was not in the metric registry.
  test("a backend that does not answer is unreachable, not an unknown signal", async () => {
    const html = await render("vital.heart_rate");
    expect(html).not.toContain("Unknown signal");
    expect(html).toContain("did not answer");
  });

  test("a signal the answered catalog does not hold is still unknown", async () => {
    catalogUp = true;
    const html = await render("vital.unknown_thing");
    expect(html).toContain("Unknown signal");
  });
});
