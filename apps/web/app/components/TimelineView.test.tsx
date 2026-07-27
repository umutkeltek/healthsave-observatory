import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { TimelineView } from "./TimelineView";
import type { Finding, FindingCard, Moment } from "../lib/api";

const MOMENT: Moment = {
  id: 1,
  kind: "illness",
  grade: "moderate",
  title: "Mild cold",
  note: "Started Monday evening",
  start_at: "2026-07-20T18:00:00Z",
  end_at: null,
  created_at: "2026-07-20T18:05:00Z",
  updated_at: "2026-07-20T18:05:00Z",
};

function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 1,
    finding_type: "recovery",
    metric: "vital.hrv_sdnn",
    severity: "info",
    structured_data: {},
    created_at: "2026-07-22T08:00:00Z",
    card: null,
    schema_version: 0,
    ...overrides,
  };
}

function makeCard(claim: string): FindingCard {
  return {
    schema_version: 1,
    claim,
    metric: "vital.hrv_sdnn",
    finding_type: "recovery",
    current_window: null,
    baseline_window: null,
    delta: null,
    effect_size: null,
    coverage: null,
    sources: [],
    confidence: null,
    limitations: [],
    confounders: [],
    next_question: null,
  };
}

describe("TimelineView", () => {
  test("renders an empty state when there are no events", () => {
    const html = renderToStaticMarkup(<TimelineView moments={[]} findings={[]} />);
    expect(html).toContain("No moments or findings");
  });

  test("renders a moment with its kind icon and grade suffix", () => {
    const html = renderToStaticMarkup(<TimelineView moments={[MOMENT]} findings={[]} />);
    expect(html).toContain("Mild cold");
    expect(html).toContain("🤒");
    expect(html).toContain(" · moderate");
    expect(html).toContain("Started Monday evening");
  });

  test("renders a finding using the typed FindingCard claim", () => {
    const finding = makeFinding({
      card: makeCard("Your HRV is 12% below your baseline."),
    });
    const html = renderToStaticMarkup(<TimelineView moments={[]} findings={[finding]} />);
    expect(html).toContain("Your HRV is 12% below your baseline.");
    expect(html).toContain("🔍");
  });

  test("renders a finding with a legacy structured_data.claim", () => {
    const finding = makeFinding({
      card: null,
      structured_data: { claim: "Legacy prose: HRV dropped 12%." },
    });
    const html = renderToStaticMarkup(<TimelineView moments={[]} findings={[finding]} />);
    expect(html).toContain("Legacy prose: HRV dropped 12%.");
  });

  test("falls back to 'type · metric' when neither card nor structured_data has a claim", () => {
    const html = renderToStaticMarkup(
      <TimelineView moments={[]} findings={[makeFinding()]} />,
    );
    expect(html).toContain("recovery · vital.hrv_sdnn");
  });

  test("interleaves moments and findings in descending time order", () => {
    const newerMoment: Moment = { ...MOMENT, id: 2, start_at: "2026-07-23T10:00:00Z", title: "Better day" };
    const olderMoment = { ...MOMENT, id: 3, start_at: "2026-07-19T08:00:00Z", title: "Rough night" };
    const finding = makeFinding({
      created_at: "2026-07-22T08:00:00Z",
      card: makeCard("Mid-window finding"),
    });
    const html = renderToStaticMarkup(
      <TimelineView moments={[olderMoment, newerMoment]} findings={[finding]} />,
    );
    const posNewer = html.indexOf("Better day");
    const posFinding = html.indexOf("Mid-window finding");
    const posOlder = html.indexOf("Rough night");
    // Newest event first (2026-07-23 moment), then finding, then oldest moment.
    expect(posNewer).toBeLessThan(posFinding);
    expect(posFinding).toBeLessThan(posOlder);
  });
});
