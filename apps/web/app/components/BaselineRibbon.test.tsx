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
