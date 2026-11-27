// Review of the round-2 fixes: the new catalog messages (pin limit, Today
// eviction, empty view, name limit) sat next to hard-coded English ("Pin",
// "Remove", the pin button's labels and fallback), so a preview locale showed
// half English. Every string in those blocks now comes from the catalog.
import { describe, expect, test } from "bun:test";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { getDictionary } from "../lib/i18n";
import { ExplorePanelCard } from "./ExplorePanelCard";
import { SavedViews, SaveToToday } from "./ExploreControls";
import { I18nProvider } from "./I18nProvider";
import { PinButton } from "./PinButton";

const noop = () => {};
const router = { refresh: noop, push: noop, replace: noop, back: noop, forward: noop, prefetch: noop } as unknown as AppRouterInstance;
const en = getDictionary("en");
const ja = getDictionary("ja");

// Every English string of the blocks under test, placeholders cut off.
const ENGLISH = [...Object.values(en.explore), ...Object.values(en.prefs)].map((text) => text.split("{")[0].trim()).filter(Boolean);

function inJapanese(node: ReactNode): string {
  return renderToStaticMarkup(
    <AppRouterContext.Provider value={router}>
      <I18nProvider locale="ja" availableLocales={["en", "ja"]}>
        {node}
      </I18nProvider>
    </AppRouterContext.Provider>,
  );
}

function expectNoEnglish(html: string) {
  for (const english of ENGLISH) expect(html).not.toContain(english);
}

describe("Explore and Today copy follows the interface language", () => {
  test("the saved-views and Pin to Today controls", () => {
    const html = inJapanese(
      <>
        <SavedViews current="range=30d" />
        <SaveToToday current="range=30d" empty={false} />
      </>,
    );
    expect(html).toContain(ja.explore.pin);
    expect(html).toContain(ja.explore.save);
    expectNoEnglish(html);
  });

  test("the pin star", () => {
    const html = inJapanese(<PinButton metricId="vital.hrv_sdnn" pinned={false} />);
    expect(html).toContain(ja.explore.pinToToday);
    expectNoEnglish(html);
  });

  test("a saved view card on Today, empty or not", async () => {
    const empty = renderToStaticMarkup(
      await ExplorePanelCard({ id: "p1", label: "空", encodedState: "range=30d&panels=", dict: ja }),
    );
    expect(empty).toContain(ja.prefs.emptySaved);
    expect(empty).toContain(ja.explore.remove);
    expectNoEnglish(empty);
  });
});
