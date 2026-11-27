import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { DivergenceLog } from "./DivergenceLog";

describe("DivergenceLog on live data", () => {
  // Detection is not wired to an API, so the log cannot know there is no
  // conflict. It used to say "No source conflict is flagged".
  test("never claims the sources agree", () => {
    const html = renderToStaticMarkup(<DivergenceLog divergences={[]} live />);
    expect(html).not.toContain("No source conflict");
    expect(html).toContain("does not mean the sources agree");
    expect(html).toContain('href="/compare?mode=source"');
  });
});
