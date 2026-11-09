// The bug (audit web #21): each URL-state page was parsed twice. The server
// validated the query (an unknown range fell back to the page default, a
// malformed signal id was dropped) while the client controls re-read the raw
// query with their own defaults, so the controls could show a range or signal
// the page was not showing.
import { describe, expect, test } from "bun:test";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { PathnameContext, SearchParamsContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { CompareControls } from "./CompareControls";
import { FilterBar } from "./FilterBar";
import { RelateControls } from "./RelateControls";

const noop = () => {};
const router = { refresh: noop, push: noop, replace: noop, back: noop, forward: noop, prefetch: noop } as unknown as AppRouterInstance;
const METRICS = [
  { id: "vital.hrv_sdnn", display_name: "HRV", category: "vital" },
  { id: "vital.resting_heart_rate", display_name: "Resting HR", category: "vital" },
];

function render(path: string, query: string, node: ReactNode): string {
  return renderToStaticMarkup(
    <AppRouterContext.Provider value={router}>
      <PathnameContext.Provider value={path}>
        <SearchParamsContext.Provider value={new URLSearchParams(query)}>{node}</SearchParamsContext.Provider>
      </PathnameContext.Provider>
    </AppRouterContext.Provider>,
  );
}

const selected = (html: string) => [...html.matchAll(/<option[^>]*value="([^"]*)"[^>]*selected=""/g)].map((m) => m[1]);

describe("URL controls show what the page shows", () => {
  test("Compare: a range the page rejected shows the range the page used", () => {
    const html = render(
      "/compare",
      "range=5y&mode=bogus",
      <CompareControls
        metrics={METRICS}
        ranges={["7d", "30d", "90d"]}
        selected={{ metric: "vital.hrv_sdnn", mode: "period", range: "30d" }}
      />,
    );
    expect(selected(html)).toEqual(["vital.hrv_sdnn", "period", "30d"]);
  });

  test("Data: the filter bar shows the page's range and says nothing is filtered", () => {
    const html = render(
      "/data",
      "range=5y",
      <FilterBar
        metrics={METRICS}
        categories={["vital"]}
        sources={[]}
        devices={[]}
        ranges={["24h", "7d", "30d"]}
        defaultRange="7d"
        selected={{ range: "7d", category: "", metric: "", source: "", device: "", sort: "" }}
      />,
    );
    expect(selected(html)).toContain("7d");
    expect(html).not.toContain("filter-clear");
  });

  test("Relationships: a malformed signal id the page dropped is not shown as chosen", () => {
    const html = render(
      "/relationships",
      "a=NOT%20AN%20ID&b=vital.hrv_sdnn&range=5y",
      <RelateControls metrics={METRICS} ranges={["30d", "90d"]} selected={{ a: "", b: "vital.hrv_sdnn", range: "90d" }} />,
    );
    expect(selected(html)).toEqual(["", "vital.hrv_sdnn", "90d"]);
  });
});
