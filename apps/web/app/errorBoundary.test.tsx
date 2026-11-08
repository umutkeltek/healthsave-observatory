import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import ErrorBoundary from "./error";

describe("route error boundary", () => {
  test("an expired session is shown as signed out with a way back, not as a UI bug", () => {
    const html = renderToStaticMarkup(<ErrorBoundary error={new Error("sign_in_required")} reset={() => {}} />);
    expect(html).not.toContain("UI bug");
    expect(html).toContain("Sign in again");
    expect(html).toContain('href="/login');
  });

  test("a genuine render error keeps the UI-bug card", () => {
    const html = renderToStaticMarkup(<ErrorBoundary error={new Error("x is undefined")} reset={() => {}} />);
    expect(html).toContain("UI bug");
  });
});
