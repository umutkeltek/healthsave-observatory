import { expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { SourceDistribution } from "./SourceDistribution";

test("renders a friendly source label instead of the canonical source UUID", () => {
  const sourceId = "a9b1e7e0-0000-4000-8000-000000000001";

  const html = renderToStaticMarkup(
    <SourceDistribution
      dist={[{ source_id: sourceId, count: 12 }]}
      sourceLabels={{ [sourceId]: "Apple Health" }}
    />,
  );

  expect(html).toContain("Apple Health");
  expect(html).not.toContain(sourceId);
});
