import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { BaselineRibbon } from "./BaselineRibbon";
import { buildScrubSeries } from "./chart/dayScrub";

describe("BaselineRibbon", () => {
  test("renders a dense trace through the final point without dash normalization", () => {
    const values = Array.from({ length: 60 }, (_, index) =>
      index % 2 === 0 ? 1_000 + index : 9_000 - index,
    );

    const html = renderToStaticMarkup(<BaselineRibbon values={values} />);
    const trace = html.match(/<path class="ribbon-trace"([^>]*)>/)?.[1];

    expect(trace).toBeDefined();
    expect(trace).toContain("L 1000.0");
    expect(trace).not.toContain("pathLength");
  });
});

test("daily ribbon preserves elapsed time and leaves missing days disconnected", () => {
  const html = renderToStaticMarkup(
    <BaselineRibbon
      values={[40, 50, 60]}
      timestamps={["2026-10-01", "2026-10-02", "2026-10-05"]}
    />,
  );
  const path = html.match(/class="ribbon-trace" d="([^"]+)"/)?.[1];
  expect(path).toContain("M 0.0 ");
  expect(path).toContain("L 250.0 ");
  expect(path).toContain("M 1000.0 ");
});

test("ribbon without timestamps keeps its existing evenly spaced layout", () => {
  const html = renderToStaticMarkup(<BaselineRibbon values={[40, 50, 60]} />);
  expect(html.match(/class="ribbon-trace" d="([^"]+)"/)?.[1]).toContain(
    "L 500.0 ",
  );
});

test("per-day ribbon breaks the line at a missing day and never bridges it", () => {
  const scrub = buildScrubSeries({
    dates: ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"],
    readings: [
      { date: "2026-11-02", value: 60 },
      { date: "2026-11-03", value: 62 },
      { date: "2026-11-05", value: 58 },
    ],
    band: [59, 61],
    unit: "ms",
    format: (v) => String(v),
  });
  const html = renderToStaticMarkup(<BaselineRibbon values={[]} scrub={scrub} />);
  const path = html.match(/class="ribbon-trace" d="([^"]+)"/)?.[1] ?? "";
  // Days 0-1 join; day 2 is missing, so day 3 starts a new piece; day 4 is empty.
  expect(path.match(/M/g)?.length).toBe(2);
  expect(path).toContain("M 0.0 ");
  expect(path).toContain("L 250.0 ");
  expect(path).toContain("M 750.0 ");
  expect(path).not.toContain("1000.0");
  // A reading with gaps on both sides has no segment, so it gets a mark.
  expect(html.match(/class="ribbon-lone"/g)?.length).toBe(1);
  // The usual range is labelled on the band, not on a value gutter.
  expect(html).toContain(">61</span>");
  expect(html).toContain(">59</span>");
  expect(html).not.toContain("ribbon-yaxis");
  // Monday Nov 2 gets a week line.
  expect(html.match(/class="ribbon-week"/g)?.length).toBe(1);
});

