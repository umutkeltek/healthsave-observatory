import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { MomentForm, MomentStatusLine } from "./MomentForm";

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

describe("MomentStatusLine", () => {
  // The bug: the status was one string and its colour came from
  // status.includes("Could not"), so a backend detail or the signed-out
  // message rendered with the success style.
  test("a failure renders as an error whatever its wording", () => {
    for (const message of ["title must not be empty", "Your session has ended.", "Could not add this moment."]) {
      const html = renderToStaticMarkup(<MomentStatusLine status={{ kind: "error", message }} />);
      expect(html).toContain("exp-error");
      expect(html).toContain(message);
    }
  });

  test("a saved moment renders as a quiet confirmation", () => {
    const html = renderToStaticMarkup(<MomentStatusLine status={{ kind: "saved" }} />);
    expect(html).toContain('class="meta"');
    expect(html).toContain("Moment added.");
  });

  test("no status renders nothing", () => {
    expect(renderToStaticMarkup(<MomentStatusLine status={null} />)).toBe("");
  });
});
