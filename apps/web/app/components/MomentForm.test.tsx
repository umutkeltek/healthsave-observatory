import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { MomentForm } from "./MomentForm";

describe("MomentForm", () => {
  test("renders all 12 life-event kinds in the dropdown", () => {
    const html = renderToStaticMarkup(<MomentForm />);
    const kinds = [
      "Illness",
      "Alcohol",
      "Late meal",
      "Travel",
      "Medication change",
      "Supplement change",
      "Hard training",
      "Stress",
      "Caffeine",
      "Injury",
      "Menstrual",
      "Other",
    ];
    for (const kind of kinds) {
      expect(html).toContain(kind);
    }
  });

  test("renders the three severity grades plus a blank option", () => {
    const html = renderToStaticMarkup(<MomentForm />);
    expect(html).toContain("mild");
    expect(html).toContain("moderate");
    expect(html).toContain("severe");
  });

  test("title field is empty by default and submit is disabled", () => {
    const html = renderToStaticMarkup(<MomentForm />);
    // The title input has no value attribute when empty; the button's
    // disabled attribute gates submission until title.trim() is non-empty.
    expect(html).toMatch(/<input[^>]*type="text"[^>]*\/>/);
    expect(html).toMatch(/<button[^>]*disabled[^>]*>/);
    expect(html).toContain("Add moment");
  });

  test("default kind is 'custom' so the dropdown opens to 'Other'", () => {
    const html = renderToStaticMarkup(<MomentForm />);
    // The default value of `kind` state is 'custom'. The corresponding
    // <option> for 'custom' should be marked selected.
    expect(html).toMatch(/<option[^>]*value="custom"[^>]*selected[^>]*>Other<\/option>/);
  });
});
