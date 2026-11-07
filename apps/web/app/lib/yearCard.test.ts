import { describe, expect, test } from "bun:test";

import { daysInYear } from "./year";
import { CARD_HEIGHT, CARD_WIDTH, cardTexts, parseCardOptions, renderYearCard } from "./yearCard";
import { yearFixture } from "./yearFixture";

const count = (svg: string, needle: RegExp) => (svg.match(needle) ?? []).length;

function visibleWords(svg: string): string[] {
  const aria = /aria-label="([^"]*)"/.exec(svg)?.[1] ?? "";
  return [...cardTexts(svg), aria];
}

describe("the share card never carries a number the person did not opt into", () => {
  const summary = yearFixture();

  test("default card: the year is the only number on it", () => {
    const svg = renderYearCard(summary, parseCardOptions(new URLSearchParams()));
    const words = visibleWords(svg);
    expect(words.some((w) => w.includes("2025"))).toBe(true);
    for (const word of words) {
      // Strip the year itself; anything numeric left over is a leak.
      expect(word.replaceAll("2025", "")).not.toMatch(/\d/);
    }
    // Nor hidden in the file: no dates in attributes (coordinates are the
    // only digits allowed outside the year).
    for (const leak of ["2025-04-10", "2025-08-03", "2025-12-31"]) expect(svg).not.toContain(leak);
  });

  test("default card: no device name, anywhere in the file", () => {
    const svg = renderYearCard(summary, { numbers: false, devices: false });
    expect(svg).not.toContain("Apple Watch");
    expect(svg).not.toContain("Oura");
    expect(svg).not.toContain("Sam");
  });

  test("numbers opt-in shows only the record counts, never a health value", () => {
    const svg = renderYearCard(summary, { numbers: true, devices: false });
    const words = cardTexts(svg);
    expect(words).toContain(String(summary.days_with_data));
    expect(words).toContain("2");
    expect(words).toContain("9");
    // Record counts only: a median from one device is a health value and
    // stays on the page.
    const printed = visibleWords(svg).flatMap((w) => w.replaceAll(",", "").match(/\d+/g) ?? []);
    for (const value of ["56", "50", "8437", "8440", "52", "61"]) expect(printed).not.toContain(value);
    expect(svg).not.toContain("Apple Watch");
  });

  test("devices opt-in names devices by month, escaped, and adds no numbers", () => {
    const svg = renderYearCard(summary, { numbers: false, devices: true });
    expect(svg).toContain("Oura &lt;Ring&gt; &amp; Co from April");
    expect(svg).not.toContain("<Ring>");
    for (const word of visibleWords(svg)) expect(word.replaceAll("2025", "")).not.toMatch(/\d/);
  });

  test("synthetic label cannot be switched on from the URL", () => {
    const options = parseCardOptions(new URLSearchParams("synthetic=1&numbers=yes&devices=true"));
    expect(options).toEqual({ numbers: false, devices: false });
    expect(renderYearCard(summary, options)).not.toContain("SYNTHETIC");
    expect(renderYearCard(summary, { ...options, synthetic: true })).toContain("SYNTHETIC DATA");
  });
});

describe("the card hides no gap", () => {
  test("every day without data is drawn as a gap mark; every day with data as a line", () => {
    const summary = yearFixture();
    const svg = renderYearCard(summary);
    const zeros = [...summary.mask].filter((c) => c === "0").length;
    expect(zeros).toBe(9);
    expect(count(svg, /class="gap"/g)).toBe(zeros);
    expect(count(svg, /class="day"/g)).toBe(summary.days_in_window - zeros);
    expect(count(svg, /class="future"/g)).toBe(0);
  });

  test("a year in progress draws the rest as 'not yet', not as gaps", () => {
    const summary = yearFixture({ windowEnd: "2025-09-30" });
    const svg = renderYearCard(summary);
    const zeros = [...summary.mask].filter((c) => c === "0").length;
    expect(count(svg, /class="gap"/g)).toBe(zeros);
    expect(count(svg, /class="future"/g)).toBe(daysInYear(2025) - summary.days_in_window);
  });

  test("an empty year is all gaps, no lines", () => {
    const summary = { ...yearFixture(), mask: "0".repeat(365), day_family_counts: Array(365).fill(0), device_changes: [] };
    const svg = renderYearCard(summary);
    expect(count(svg, /class="gap"/g)).toBe(365);
    expect(count(svg, /class="day"/g)).toBe(0);
  });
});

test("card is a 1080 x 1350 SVG with twelve month marks", () => {
  const svg = renderYearCard(yearFixture());
  expect(svg.startsWith("<svg")).toBe(true);
  expect(svg).toContain(`width="${CARD_WIDTH}" height="${CARD_HEIGHT}"`);
  expect(count(svg, /class="month"/g)).toBe(12);
  expect(count(svg, /class="change"/g)).toBe(1);
});
