import { describe, expect, test } from "bun:test";
import type { ReactElement, ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { YearCardOptionsForm } from "./YearCardOptionsForm";

describe("YearCardOptionsForm", () => {
  // The bug: the boxes were plain defaultChecked inputs applied only by
  // "Update preview", so a ticked box could disagree with the preview and the
  // download (and a reload could restore a box the URL did not hold).
  test("the boxes show the URL's options and the browser does not restore other ones", () => {
    const html = renderToStaticMarkup(<YearCardOptionsForm year={2025} options={{ numbers: true, devices: false }} />);
    expect(html.toLowerCase()).toContain('autocomplete="off"');
    expect(html).toMatch(/<input type="checkbox" name="numbers" checked=""/);
    expect(html).not.toMatch(/name="devices" checked=""/);
    expect(html).toContain('action="/year/2025#yr-share-title"');
  });

  // Behaviour, not markup: each box must submit its form (the GET that moves
  // the URL, the preview and the download together) the moment it changes.
  // The form has no hooks, so its element tree can be walked and each box's
  // change handler fired with a stand-in form.
  test("changing a box submits the form at once", () => {
    const inputs: ReactElement<{ name?: string; onChange?: (event: unknown) => void }>[] = [];
    const walk = (node: ReactNode) => {
      if (Array.isArray(node)) return node.forEach(walk);
      if (!node || typeof node !== "object" || !("props" in node)) return;
      const element = node as ReactElement<{ children?: ReactNode; name?: string }>;
      if (element.type === "input") inputs.push(element);
      walk(element.props.children);
    };
    walk(YearCardOptionsForm({ year: 2025, options: { numbers: false, devices: false } }));

    expect(inputs.map((input) => input.props.name)).toEqual(["numbers", "devices"]);
    for (const input of inputs) {
      let submitted = 0;
      expect(typeof input.props.onChange).toBe("function");
      input.props.onChange?.({ currentTarget: { form: { requestSubmit: () => (submitted += 1) } } });
      expect(submitted).toBe(1);
    }
  });
});
