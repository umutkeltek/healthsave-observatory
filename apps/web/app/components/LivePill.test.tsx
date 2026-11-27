// The top-bar live pills sit in translated chrome: every state must read in
// the interface language (never mix languages).
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { dictionaries, LOCALES } from "../lib/i18n";
import { LivePill, type LiveState } from "./LiveStatus";

const STATES: LiveState[] = ["unknown", "live", "updating", "offline", "signed-out"];
const ENGLISH = [
  "updating",
  "offline",
  "signed out",
  "sign in",
  "Backend unreachable",
  "Watching for new data",
  "Polling for first response",
  "Some readings on this page",
];

describe("LivePill", () => {
  test("every state renders from the dictionary in every locale", () => {
    for (const locale of LOCALES) {
      const dict = dictionaries[locale];
      for (const state of STATES) {
        const html = renderToStaticMarkup(<LivePill state={state} dict={dict} signInHref="/login" />);
        const labels = dict.live[state === "signed-out" ? "signedOut" : state];
        expect(html).toContain(labels.aria);
        if (state !== "unknown") expect(html).toContain(labels.pill);
      }
    }
  });

  test("a non-English interface shows no English pill text", () => {
    for (const state of STATES) {
      // Class names are not shown to anyone; text, titles and aria labels are.
      const shown = renderToStaticMarkup(
        <LivePill state={state} dict={dictionaries.ja} signInHref="/login" />,
      ).replace(/ class="[^"]*"/g, "");
      for (const word of ENGLISH) expect(shown).not.toContain(word);
    }
  });

  test("signed out links to sign-in in a new tab", () => {
    const html = renderToStaticMarkup(<LivePill state="signed-out" dict={dictionaries.en} signInHref="/login?next=%2Fsleep" />);
    expect(html).toContain('href="/login?next=%2Fsleep"');
    expect(html).toContain('target="_blank"');
  });
});
