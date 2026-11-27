// The Explore "Save this view as" field (review of the #18 fix): it had no
// length limit while names over 60 characters were thrown away, so a long
// name cleared the field and saved nothing.
import { describe, expect, test } from "bun:test";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { renderToStaticMarkup } from "react-dom/server";

import { MAX_SAVED_VIEW_NAME } from "../lib/explore";
import { SavedViews } from "./ExploreControls";
import { I18nProvider } from "./I18nProvider";

const noop = () => {};
const router = { refresh: noop, push: noop, replace: noop, back: noop, forward: noop, prefetch: noop } as unknown as AppRouterInstance;

describe("saved views field", () => {
  test("the name field stops at the limit and says what the limit is", () => {
    const html = renderToStaticMarkup(
      <AppRouterContext.Provider value={router}>
        <I18nProvider locale="en" availableLocales={["en"]}>
          <SavedViews current="range=30d" />
        </I18nProvider>
      </AppRouterContext.Provider>,
    );
    expect(html).toContain(`maxLength="${MAX_SAVED_VIEW_NAME}"`);
    expect(html).toContain(`up to ${MAX_SAVED_VIEW_NAME} characters`);
  });
});
