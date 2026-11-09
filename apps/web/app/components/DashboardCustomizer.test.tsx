// The bug (audit web #20): the customizer's templates, section toggles and
// reset stayed clickable while a save was in flight. Two quick toggles each
// read the same dashboard cookie and wrote it back, so one change was lost.
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { defaultSections } from "../lib/templates";
import { CustomizerControls } from "./DashboardCustomizer";

const noop = () => {};

function render(pending: boolean): string {
  return renderToStaticMarkup(
    <CustomizerControls
      sections={defaultSections()}
      activeId={null}
      pending={pending}
      error={null}
      onTemplate={noop}
      onToggle={noop}
      onReset={noop}
    />,
  );
}

describe("dashboard customizer", () => {
  test("while a save is in flight every control that writes is disabled", () => {
    const html = render(true);
    const buttons = html.match(/<button[^>]*>/g) ?? [];
    const boxes = html.match(/<input[^>]*type="checkbox"[^>]*>/g) ?? [];
    expect(buttons.length).toBeGreaterThan(0);
    expect(boxes.length).toBeGreaterThan(1);
    for (const control of [...buttons, ...boxes]) expect(control).toContain("disabled");
    expect(html).toContain('aria-busy="true"');
  });

  test("when idle only the always-visible hero is locked", () => {
    const html = render(false);
    const disabled = (html.match(/<(?:button|input)[^>]*disabled[^>]*>/g) ?? []).length;
    expect(disabled).toBe(1);
  });
});
