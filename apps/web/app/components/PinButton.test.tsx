// A refused pin explains itself (audit web #19). The star sits in a grid cell
// of Library rows, so the button and its message must be one element, or the
// message takes a column and the row's layout breaks.
import { describe, expect, test } from "bun:test";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { renderToStaticMarkup } from "react-dom/server";

import { I18nProvider } from "./I18nProvider";
import { PinButton } from "./PinButton";

const noop = () => {};
const router = { refresh: noop, push: noop, replace: noop, back: noop, forward: noop, prefetch: noop } as unknown as AppRouterInstance;

describe("pin button", () => {
  test("renders as one element, whatever it has to say", () => {
    const html = renderToStaticMarkup(
      <AppRouterContext.Provider value={router}>
        <I18nProvider locale="en" availableLocales={["en"]}>
          <PinButton metricId="vital.hrv_sdnn" pinned={false} />
        </I18nProvider>
      </AppRouterContext.Provider>,
    );
    expect(html.startsWith('<span class="pin-control">')).toBe(true);
    expect(html.endsWith("</span>")).toBe(true);
  });
});
