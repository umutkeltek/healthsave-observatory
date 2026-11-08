// A failed read must render as "did not answer", never as demo data. The real
// sections and loaders run against a stubbed backend that fails every read.
// No module mocks (see year/yearPage.test.tsx).
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { PathnameContext, SearchParamsContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { clearSwrCache } from "../../lib/ttlCache";
import { CompareSection } from "./CompareSections";
import { ExplorerSection } from "./DataSections";
import { ComputedRelationshipsSection, correlationsState, ExplorePairSection } from "./RelationshipsSections";
import { ProvenanceSection } from "./SourcesSections";

const noop = () => {};
const router = {
  refresh: noop,
  push: noop,
  replace: noop,
  back: noop,
  forward: noop,
  prefetch: noop,
} as unknown as AppRouterInstance;

function html(node: ReactNode, path = "/"): string {
  return renderToStaticMarkup(
    <AppRouterContext.Provider value={router}>
      <PathnameContext.Provider value={path}>
        <SearchParamsContext.Provider value={new URLSearchParams()}>{node}</SearchParamsContext.Provider>
      </PathnameContext.Provider>
    </AppRouterContext.Provider>,
  );
}

const realFetch = globalThis.fetch;
const realWarn = console.warn;

beforeEach(() => {
  clearSwrCache();
  console.warn = noop;
  globalThis.fetch = (async () => Response.json({ detail: "boom" }, { status: 500 })) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = realFetch;
  console.warn = realWarn;
  clearSwrCache();
});

const DEMO = /\bdemo\b/i;

describe("a failed read never turns into demo data", () => {
  test("Data: the selected metric's patterns say the API did not answer", async () => {
    const out = html(
      await ExplorerSection({
        filters: {
          metricSel: "vital.heart_rate",
          categorySel: "",
          sourceSel: "",
          deviceSel: "",
          sortSel: "",
          range: "7d",
        },
      }),
      "/data",
    );
    expect(out).not.toMatch(DEMO);
    expect(out).toContain("did not answer");
  });

  test("Compare: no illustrative comparison stands in for the person's data", async () => {
    const out = html(await CompareSection({ metricSel: "vital.heart_rate", mode: "source", range: "30d" }), "/compare");
    expect(out).not.toMatch(DEMO);
    expect(out).not.toContain("Apple Watch");
    expect(out).toContain("did not answer");
  });

  test("Compare with no catalog and no selection: still unreachable, not a demo metric", async () => {
    const out = html(await CompareSection({ metricSel: "", mode: "period", range: "30d" }), "/compare");
    expect(out).not.toMatch(DEMO);
    expect(out).toContain("did not answer");
  });

  test("Sources: no demo provenance", async () => {
    const out = html(await ProvenanceSection(), "/sources");
    expect(out).not.toMatch(DEMO);
    expect(out).toContain("did not answer");
  });

  test("Relationships: no demo correlations and no demo pair", async () => {
    const rows = html(await ComputedRelationshipsSection({ range: "90d" }), "/relationships");
    expect(rows).not.toMatch(DEMO);
    expect(rows).toContain("did not answer");
    const pair = html(
      await ExplorePairSection({ aId: "vital.heart_rate", bId: "activity.steps", range: "90d" }),
      "/relationships",
    );
    expect(pair).not.toMatch(DEMO);
    expect(pair).not.toContain("r = ");
    expect(pair).toContain("did not answer");
  });
});

describe("withheld for a participant is not an outage", () => {
  test("correlations withheld for a participant say they cover the primary person", () => {
    expect(correlationsState(null, true)).toBe("not-for-person");
    expect(correlationsState(null, false)).toBe("unreachable");
    expect(correlationsState([], false)).toBe("data");
  });
});

describe("a metric the backend does not know is not an outage", () => {
  // The review: a 404 for an unknown metric said "The Observatory API did not
  // answer", in Compare and in the Data patterns panel.
  function backendWithoutSeries() {
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v2/metrics")) {
        return Response.json([
          { id: "vital.heart_rate", display_name: "Heart Rate", category: "vital", value_type: "numeric", canonical_unit: "bpm" },
        ]);
      }
      if (url.includes("/series")) return Response.json({ detail: "unknown metric" }, { status: 404 });
      if (url.endsWith("/api/v2/streams")) return Response.json({ count: 0, streams: [] });
      return Response.json({ detail: "boom" }, { status: 500 });
    }) as unknown as typeof fetch;
  }

  test("Compare says the signal was not found", async () => {
    backendWithoutSeries();
    const out = html(await CompareSection({ metricSel: "vital.heart_rate", mode: "period", range: "30d" }), "/compare");
    expect(out).not.toContain("did not answer");
    expect(out).toContain("No signal called");
  });

  test("Data's patterns panel and card say the signal was not found", async () => {
    backendWithoutSeries();
    const out = html(
      await ExplorerSection({
        filters: { metricSel: "vital.heart_rate", categorySel: "", sourceSel: "", deviceSel: "", sortSel: "", range: "7d" },
      }),
      "/data",
    );
    expect(out).not.toContain("did not answer");
    expect(out).toContain("No signal called");
  });
});
