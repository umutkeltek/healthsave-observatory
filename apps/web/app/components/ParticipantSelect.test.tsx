import { describe, expect, test } from "bun:test";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { renderToStaticMarkup } from "react-dom/server";

import { DEFAULT_OWNER_ID, switcherModel, type ViewedPerson } from "../lib/participants";
import { I18nProvider } from "./I18nProvider";
import { ParticipantSelect } from "./ParticipantSelect";

// The select calls useRouter(), which needs an app router in context; outside
// Next none is mounted, so the test provides a stub. Nothing is mocked at the
// module level: bun applies a module mock to every test file that runs after
// it, and other files import useSearchParams from next/navigation.
const noop = () => {};
const router = {
  refresh: noop,
  push: noop,
  replace: noop,
  back: noop,
  forward: noop,
  prefetch: noop,
} as unknown as AppRouterInstance;

const ALICE = "7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00";
const BOB = "2f4a9c1e-6d3b-4e8f-8a2c-5b7d9e0f1a2b";
const OWNERS = [
  { id: DEFAULT_OWNER_ID, label: null, isDefault: true, active: true },
  { id: ALICE, label: "Alice Smith", isDefault: false, active: true },
  { id: BOB, label: "Bob", isDefault: false, active: false },
];

function render(current: string): string {
  return renderToStaticMarkup(
    <AppRouterContext.Provider value={router}>
      <I18nProvider locale="en" availableLocales={["en"]}>
        <ParticipantSelect owners={OWNERS} current={current} />
      </I18nProvider>
    </AppRouterContext.Provider>,
  );
}

describe("ParticipantSelect", () => {
  test("lists the primary person first, then participants, revoked ones marked", () => {
    const html = render(DEFAULT_OWNER_ID);
    const options = [...html.matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map((m) => m[1]);
    expect(options).toEqual(["Primary person", "Alice Smith", "Bob (revoked)"]);
    expect(html).toContain("Viewing");
  });

  test("the primary view carries no primary-only note", () => {
    expect(render(DEFAULT_OWNER_ID)).not.toContain("primary person only");
  });

  test("a participant view selects that person and says what stays primary-only", () => {
    const html = render(ALICE);
    expect(html).toMatch(new RegExp(`<option value="${ALICE}" selected="">Alice Smith</option>`));
    expect(html).toContain("Findings, experiments and briefs cover the primary person only.");
  });

  // The switcher renders from the same decision the reads use.
  function renderFor(person: ViewedPerson, owners: Parameters<typeof switcherModel>[1]): string {
    const model = switcherModel(person, owners);
    return renderToStaticMarkup(
      <AppRouterContext.Provider value={router}>
        <I18nProvider locale="en" availableLocales={["en"]}>
          <ParticipantSelect
            owners={model.options}
            current={model.current}
            notice={model.notice}
            clearCookie={model.clearCookie}
          />
        </I18nProvider>
      </AppRouterContext.Provider>,
    );
  }
  const PRIMARY_ROW = { id: DEFAULT_OWNER_ID, label: null, is_default: true, active: true };

  test("a cookie naming someone no longer listed says the view moved to the primary person", () => {
    const html = renderFor({ kind: "unlisted", requested: ALICE }, [PRIMARY_ROW]);
    expect(html).toContain("no longer on this Observatory. Showing the primary person.");
    expect(html).not.toContain("<select");
  });

  test("a failed owner list still names the person being read, and offers the way back", () => {
    const html = renderFor({ kind: "unverified", owner: ALICE }, null);
    expect(html).toMatch(new RegExp(`<option value="${ALICE}" selected="">${ALICE.slice(0, 8)}</option>`));
    expect(html).toContain(`<option value="${DEFAULT_OWNER_ID}">Primary person</option>`);
    expect(html).toContain("Could not load the list of people");
  });

  test("a single-person install with no cookie renders nothing", () => {
    expect(renderFor({ kind: "primary" }, [PRIMARY_ROW])).toBe("");
  });
});
