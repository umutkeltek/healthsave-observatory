// A refused pin explains itself (audit web #19). The star sits in a grid cell
// of Library rows, so the button and its message must be one element, or the
// message takes a column and the row's layout breaks.
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { PinButton } from "./PinButton";

describe("pin button", () => {
  test("renders as one element, whatever it has to say", () => {
    const html = renderToStaticMarkup(<PinButton metricId="vital.hrv_sdnn" pinned={false} />);
    expect(html.startsWith('<span class="pin-control">')).toBe(true);
    expect(html.endsWith("</span>")).toBe(true);
  });
});
