// The bug (audit web #17): the sidebar (via Shell) and Settings each kept
// their own optimistic copy of the density. A pick in one never reached the
// other, and a local pick never yielded to the server, so the two could show
// different modes at once.
import { describe, expect, test } from "bun:test";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { renderToStaticMarkup } from "react-dom/server";

import type { Density } from "../lib/prefs";
import { DensityProvider, StandaloneDensityToggle } from "./DensityToggle";
import { I18nProvider } from "./I18nProvider";

const noop = () => {};
const router = { refresh: noop, push: noop, replace: noop, back: noop, forward: noop, prefetch: noop } as unknown as AppRouterInstance;

function activeButton(html: string): string | undefined {
  return /<button[^>]*class="active"[^>]*>([^<]*)<\/button>/.exec(html)?.[1];
}

function render(node: React.ReactNode): string {
  return renderToStaticMarkup(
    <AppRouterContext.Provider value={router}>
      <I18nProvider locale="en" availableLocales={["en"]}>
        {node}
      </I18nProvider>
    </AppRouterContext.Provider>,
  );
}

describe("density has one owner", () => {
  test("the Settings toggle shows the shell's density, not a copy of its own", () => {
    const shell = { density: "essentials" as Density, pick: noop };
    const html = render(
      <DensityProvider value={shell}>
        <StandaloneDensityToggle density="observatory" />
      </DensityProvider>,
    );
    expect(activeButton(html)).toBe("Essentials");
  });

  test("outside the shell the toggle still shows the server's value", () => {
    expect(activeButton(render(<StandaloneDensityToggle density="observatory" />))).toBe("Observatory");
  });
});
