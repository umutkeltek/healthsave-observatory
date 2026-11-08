import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { YearCardOptionsForm } from "./YearCardOptionsForm";

describe("YearCardOptionsForm", () => {
  // The bug: the boxes were plain defaultChecked inputs applied only by
  // "Update preview", so a ticked box could disagree with the preview and the
  // download (and a reload could restore a box the URL did not hold).
  test("the boxes show the URL's options and the browser does not restore other ones", () => {
    const html = renderToStaticMarkup(<YearCardOptionsForm year={2025} options={{ numbers: true, devices: false }} />);
    expect(html.toLowerCase()).toContain('autocomplete="off"');
    expect(html).toMatch(/<input type="checkbox" name="numbers" checked=""/);
    expect(html).not.toMatch(/name="devices" checked=""/);
    expect(html).toContain('action="/year/2025#yr-share-title"');
  });
});
