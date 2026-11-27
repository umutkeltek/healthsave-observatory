// A refused pin explains itself (audit web #19). The star sits in a grid cell
// of Library rows, so the star and its message must be ONE element, or the
// message takes the next column and the row's layout breaks.
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { PinControl } from "./PinButton";

const REFUSED = "You can pin up to 16 signals. Unpin one first.";

describe("pin control", () => {
  test("with a message, star and message are one element", () => {
    const html = renderToStaticMarkup(
      <PinControl pinned={false} pending={false} error={REFUSED} label="Pin to Today" onPick={() => {}} />,
    );
    expect(html).toMatch(
      new RegExp(`^<span class="pin-control"><button[^>]*>[\\s\\S]*</button><span class="pin-error"[^>]*>${REFUSED}</span></span>$`),
    );
  });

  test("without a message, only the star inside the same element", () => {
    const html = renderToStaticMarkup(
      <PinControl pinned pending={false} error={null} label="Unpin from Today" onPick={() => {}} />,
    );
    expect(html).toMatch(/^<span class="pin-control"><button[^>]*aria-label="Unpin from Today"[^>]*>[\s\S]*<\/button><\/span>$/);
  });
});
