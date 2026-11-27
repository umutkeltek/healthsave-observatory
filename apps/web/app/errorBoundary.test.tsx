import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import ErrorBoundary from "./error";
import GlobalError, { savedTheme } from "./global-error";

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

// The bug (audit web #23, third part): the last-resort error page hardcoded
// data-theme="dark", so a person on the light default (or who chose light)
// was dropped into the dark theme exactly when something had gone wrong.
describe("global error page", () => {
  test("follows the saved theme, light by default", () => {
    expect(savedTheme(undefined)).toBe("light");
    expect(savedTheme({ getItem: () => null })).toBe("light");
    expect(savedTheme({ getItem: () => "dark" })).toBe("dark");
    expect(savedTheme({ getItem: () => "neon" })).toBe("light");
    const html = renderToStaticMarkup(<GlobalError error={new Error("boom")} reset={() => {}} />);
    expect(html).toContain('data-theme="light"');
    expect(html).not.toContain('data-theme="dark"');
  });

  test("uses the design tokens' sign-in card, not inline styling", () => {
    const html = renderToStaticMarkup(<GlobalError error={new Error("boom")} reset={() => {}} />);
    expect(html).toContain('class="signin"');
    expect(html).not.toContain("style=");
  });
});
