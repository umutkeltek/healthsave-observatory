import { expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { SeriesPoint } from "../lib/api";

import { DataTable } from "./DataTable";

test("renders a friendly source label instead of the canonical source UUID", () => {
  const sourceId = "a9b1e7e0-0000-4000-8000-000000000001";
  const points: SeriesPoint[] = [
    {
      t: "2026-09-11T12:00:00Z",
      value: 42,
      code: null,
      unit: "mL/kg/min",
      source_id: sourceId,
      stream_id: "11111111-1111-4111-8111-111111111111",
      confidence: null,
    },
  ];

  const html = renderToStaticMarkup(
    <DataTable points={points} unit="mL/kg/min" sourceLabels={{ [sourceId]: "Apple Health" }} />,
  );

  expect(html).toContain("Apple Health");
  expect(html).not.toContain(sourceId);
});
