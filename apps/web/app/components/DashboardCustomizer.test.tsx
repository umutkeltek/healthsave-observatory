// The dashboard customizer writes one cookie per click (audit web #20): a
// second write must not start while one is in flight. Review of the first fix:
// disabling the focused control dropped focus to <body>, so Escape and the Tab
// trap (listened for on the sheet) stopped working; and the test passed
// `pending` by hand, so the component's own wiring was never exercised.
import { describe, expect, test } from "bun:test";
import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { renderToStaticMarkup } from "react-dom/server";

import { defaultSections } from "../lib/templates";
import { WriteGate } from "../lib/writeGate";
import { DashboardCustomizer } from "./DashboardCustomizer";

const noop = () => {};
const router = { refresh: noop, push: noop, replace: noop, back: noop, forward: noop, prefetch: noop } as unknown as AppRouterInstance;

function renderOpen(gate: WriteGate): string {
  return renderToStaticMarkup(
    <AppRouterContext.Provider value={router}>
      <DashboardCustomizer sections={defaultSections()} initiallyOpen gate={gate} />
    </AppRouterContext.Provider>,
  );
}

const controls = (html: string) => [
  ...(html.match(/<button[^>]*class="template-card[^"]*"[^>]*>/g) ?? []),
  ...(html.match(/<input[^>]*type="checkbox"[^>]*>/g) ?? []),
  ...(html.match(/<button[^>]*dashboard-reset-btn[^>]*>/g) ?? []),
];

describe("dashboard customizer", () => {
  test("while a write is in flight, every writing control is unavailable but keeps focus", () => {
    const gate = new WriteGate();
    void gate.run(() => new Promise(() => {}));
    const html = renderOpen(gate);
    const writing = controls(html).filter((tag) => !tag.includes('data-section="hero"'));
    expect(writing.length).toBeGreaterThan(4);
    expect(html).toContain('aria-busy="true"');
    // Unavailable to the click, but never `disabled`: a disabled control loses
    // focus, and the sheet's keyboard handling with it. (The hero row is the
    // one control that is always disabled; it never takes focus.)
    for (const tag of writing) {
      expect(tag).toContain('aria-disabled="true"');
      expect(tag).not.toMatch(/ disabled=""/);
    }
  });

  test("when no write is in flight nothing is marked unavailable", () => {
    const html = renderOpen(new WriteGate());
    expect(html).not.toContain('aria-disabled="true"');
    expect(html).toContain('aria-busy="false"');
  });
});

describe("write gate", () => {
  test("refuses a second write while one is in flight, then opens again", async () => {
    const gate = new WriteGate();
    let finish: () => void = noop;
    const first = gate.run(() => new Promise<string>((resolve) => (finish = () => resolve("saved"))));
    expect(gate.isBusy()).toBe(true);
    let secondRan = false;
    expect(
      await gate.run(async () => {
        secondRan = true;
        return "second";
      }),
    ).toBeNull();
    expect(secondRan).toBe(false);
    finish();
    expect(await first).toBe("saved");
    expect(gate.isBusy()).toBe(false);
    expect(await gate.run(async () => "third")).toBe("third");
  });

  test("tells subscribers when it opens and closes, and opens again after a failed write", async () => {
    const gate = new WriteGate();
    const seen: boolean[] = [];
    const unsubscribe = gate.subscribe(() => seen.push(gate.isBusy()));
    await gate.run(async () => {
      throw new Error("boom");
    }).catch(noop);
    unsubscribe();
    expect(seen).toEqual([true, false]);
    expect(gate.isBusy()).toBe(false);
  });
});
