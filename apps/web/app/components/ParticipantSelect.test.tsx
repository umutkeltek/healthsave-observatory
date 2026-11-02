import { describe, expect, mock, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

// The select refreshes the router after its server action; no app router is
// mounted outside Next, and rendering never invokes it.
mock.module("next/navigation", () => ({ useRouter: () => ({ refresh() {} }) }));

const { I18nProvider } = await import("./I18nProvider");
const { ParticipantSelect } = await import("./ParticipantSelect");
const { DEFAULT_OWNER_ID } = await import("../lib/participants");

const ALICE = "7d0c4f8e-2b6a-4a51-9a7e-0d6a3c2b1f00";
const BOB = "2f4a9c1e-6d3b-4e8f-8a2c-5b7d9e0f1a2b";
const OWNERS = [
  { id: DEFAULT_OWNER_ID, label: null, isDefault: true, active: true },
  { id: ALICE, label: "Alice Smith", isDefault: false, active: true },
  { id: BOB, label: "Bob", isDefault: false, active: false },
];

function render(current: string): string {
  return renderToStaticMarkup(
    <I18nProvider locale="en" availableLocales={["en"]}>
      <ParticipantSelect owners={OWNERS} current={current} />
    </I18nProvider>,
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
});
