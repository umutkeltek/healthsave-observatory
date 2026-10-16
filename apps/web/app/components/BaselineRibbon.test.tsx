import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { BaselineRibbon } from "./BaselineRibbon";

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
