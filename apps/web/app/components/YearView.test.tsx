import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { yearFixture } from "../lib/yearFixture";
import { YearView } from "./YearView";

const render = (summary = yearFixture(), options = { numbers: false, devices: false }) =>
  renderToStaticMarkup(<YearView year={2025} summary={summary} options={options} />);

const count = (html: string, needle: RegExp) => (html.match(needle) ?? []).length;

describe("Year view hides no gap", () => {
  test("every day without data is a gap cell in the month calendars", () => {
    const summary = yearFixture();
    const html = render(summary);
    const zeros = [...summary.mask].filter((c) => c === "0").length;
    expect(count(html, /class="yr-cell is-gap"/g)).toBe(zeros + 1); // + the legend swatch
  });

  test("every gap run of every kind of data is listed, with all its days", () => {
    const summary = yearFixture();
    const html = render(summary);
    const listed = [...html.matchAll(/data-gap-days="(\d+)"/g)].map((m) => Number(m[1]));
    const expected = [...summary.families.flatMap((f) => f.gaps), ...summary.gaps].map((g) => g.days);
    expect(listed.sort()).toEqual(expected.sort());
    for (const family of summary.families) {
      const total = family.gaps.reduce((n, g) => n + g.days, 0);
      expect(total).toBe(family.days_without_data);
    }
    expect(html).toContain("9 days with nothing recorded: Aug 3 – Aug 11.");
    expect(html).toContain("Nothing yet before Apr 10: Jan 1 – Apr 9, 99 days.");
  });

  test("each day strip draws gap runs as their own shapes", () => {
    const html = render();
    expect(count(html, /class="yr-run-gap"/g)).toBeGreaterThan(0);
  });
});

describe("Year view content", () => {
  test("two sources keep two numbers; nothing in between", () => {
    const html = render();
    expect(html).toContain("56 bpm");
    expect(html).toContain("50 bpm");
    expect(html).not.toContain("53 bpm");
    expect(html).toContain("Two devices are never blended into one number.");
    expect(html).toContain("Resting heart rate, Old Scale: 4 days this year, too few for a number (needs 7).");
  });

  test("months show coverage, sources, the new device and low confidence", () => {
    const html = render();
    expect(html).toContain("New: Oura &lt;Ring&gt; &amp; Co");
    expect(html).toContain("Low confidence");
    expect(count(html, /class="yr-month /g)).toBe(12);
    expect(html).toContain("New this year");
  });

  test("limitations are always shown", () => {
    const html = render();
    expect(html).toContain("What this view cannot tell you");
    expect(html).toContain("Days are counted in Europe/Istanbul, and each day starts at 04:00");
  });

  test("the card preview asks for no numbers and no device names unless opted in", () => {
    expect(render()).toContain('src="/year/2025/card"');
    expect(render(yearFixture(), { numbers: true, devices: false })).toContain('src="/year/2025/card?numbers=1"');
    const both = render(yearFixture(), { numbers: true, devices: true });
    expect(both).toContain('src="/year/2025/card?numbers=1&amp;devices=1"');
    expect(both).toMatch(/name="numbers" checked=""/);
    expect(render()).not.toMatch(/name="numbers" checked=""/);
  });

  test("an unreachable API says so instead of drawing an empty year", () => {
    const html = renderToStaticMarkup(<YearView year={2025} summary={null} options={{ numbers: false, devices: false }} />);
    expect(html).toContain("did not answer");
    expect(html).not.toContain("yr-month");
  });

  test("a year with nothing says so and still shows its limits", () => {
    const empty = {
      ...yearFixture(),
      days_with_data: 0,
      families: [],
      sources: [],
      device_changes: [],
      limitations: [{ code: "no_data", day: null, count: null }],
    };
    const html = render(empty);
    expect(html).toContain("Nothing recorded in 2025");
    expect(html).toContain("There is no data for this year on this Observatory.");
  });
});
