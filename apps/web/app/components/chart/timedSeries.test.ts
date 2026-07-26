import { describe, expect, test } from "bun:test";

import { timedDomain, timedSegments } from "./timedSeries";

describe("timestamp-faithful chart series", () => {
  test("sorts points by actual time", () => {
    const segments = timedSegments([
      { t: "2026-07-03T00:00:00Z", value: 3 },
      { t: "2026-07-01T00:00:00Z", value: 1 },
      { t: "2026-07-02T00:00:00Z", value: 2 },
    ]);
    expect(segments[0].map((point) => point.value)).toEqual([1, 2, 3]);
  });

  test("does not draw a line across a missing interval", () => {
    const segments = timedSegments([
      { t: "2026-07-01T00:00:00Z", value: 1 },
      { t: "2026-07-02T00:00:00Z", value: 2 },
      { t: "2026-07-03T00:00:00Z", value: 3 },
      { t: "2026-07-10T00:00:00Z", value: 4 },
    ]);
    expect(segments.map((segment) => segment.length)).toEqual([3, 1]);
  });

  test("derives the shared domain from every series rather than one source", () => {
    expect(
      timedDomain([
        { points: [{ t: "2026-07-03T00:00:00Z", value: 2 }] },
        {
          points: [
            { t: "2026-07-01T00:00:00Z", value: 1 },
            { t: "2026-07-05T00:00:00Z", value: 3 },
          ],
        },
      ]),
    ).toEqual(["2026-07-01T00:00:00.000Z", "2026-07-05T00:00:00.000Z"]);
  });
});
