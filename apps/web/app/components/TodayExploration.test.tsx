import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { Finding } from "../lib/api";
import type { TodayTrendOption } from "../lib/todayPresentation";
import { TodayExploration, TodayReadingTile } from "./TodayExploration";
import { TodayTrend } from "./TodayTrend";
import { TodayFindings } from "./TodayFindings";

const option: TodayTrendOption = {
  id: "activity.steps",
  title: "Steps",
  unit: "steps",
  source: "Daily totals across sources",
  kind: "daily-total",
  latestAt: "2026-10-16T00:00:00Z",
  days: [
    { date: "2026-10-15", value: 8000 },
    { date: "2026-10-16", value: 23 },
  ],
};

describe("Today exploration", () => {
  test("tiles control the in-page chart, but remain detail links when the chart is hidden", () => {
    const tile = (
      <TodayReadingTile
        id="vital.hrv_sdnn"
        title="HRV SDNN"
        className="today-metric"
      >
        143 ms
      </TodayReadingTile>
    );
    const enabled = renderToStaticMarkup(
      <TodayExploration enabled>{tile}</TodayExploration>,
    );
    expect(enabled).toContain('aria-controls="today-reading-detail"');
    expect(enabled).toContain('aria-pressed="true"');
    const hidden = renderToStaticMarkup(
      <TodayExploration enabled={false}>{tile}</TodayExploration>,
    );
    expect(hidden).toContain('href="/library/vital.hrv_sdnn"');
    expect(hidden).not.toContain("aria-controls");
  });

  test("daily totals explain partial days and expose dates and values outside the chart", () => {
    const html = renderToStaticMarkup(
      <TodayTrend options={[option]} now="2026-10-16T23:00:00Z" />,
    );
    // One answer line, the value in ink, and the partial day said out loud.
    expect(html).toContain(
      '<p class="scrub-answer"><b>23 steps</b> on Fri, Oct 16 · latest day, may be incomplete</p>',
    );
    expect(html).toContain("2 of 30 days recorded");
    expect(html).toContain("Daily totals across sources · dates in UTC");
    // The title is the picker: a real select with an accessible name.
    expect(html).toContain('<select aria-label="Reading">');
    expect(html).toContain('aria-labelledby="today-trend-title"');
    expect(html).toContain('<span id="today-trend-title">Steps</span>');
    // The per-day values stay reachable behind one quiet control.
    expect(html).toContain('aria-controls="today-trend-values"');
    expect(html).toContain("Daily values");
    expect(html).toContain("The latest day may be incomplete.");
    expect(html).toContain('<time dateTime="2026-10-16">');
    expect(html).toContain("23 steps");
    expect(html).toContain('href="/library/activity.steps?range=30d"');
  });

  test("the day ruler is a keyboard slider over every day in the window", () => {
    const html = renderToStaticMarkup(
      <TodayTrend options={[option]} now="2026-10-16T23:00:00Z" />,
    );
    expect(html).toContain('role="slider"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain('aria-valuemin="0" aria-valuemax="29" aria-valuenow="29"');
    expect(html).toContain('aria-valuetext="23 steps, Fri, Oct 16"');
    // 30 days, 2 recorded: 28 days are dots on the ruler, not filled values.
    const ticks = html.split('class="day-ruler-ticks"')[1].split("</div>")[0];
    expect(ticks.match(/is-dot/g)?.length).toBe(28);
  });

  test("the answer line keeps the height of its longest answer, so nothing below moves", () => {
    const html = renderToStaticMarkup(
      <TodayTrend options={[option]} now="2026-10-16T23:00:00Z" />,
    );
    const slot = html.split('<div class="scrub-answer-slot">')[1].split("</div>")[0];
    // The shown answer comes first; every day of the window sits behind it, unseen.
    expect(slot.startsWith('<p class="scrub-answer"><b>23 steps</b>')).toBe(true);
    const sizes = slot.match(/<p class="scrub-answer scrub-answer-size" aria-hidden="true">/g);
    expect(sizes?.length).toBe(30);
    // The short gap-day answer and the long noted one both size the line.
    expect(slot).toContain("<b>No reading</b> on Thu, Sep 17. The gap stays a gap.");
    expect(slot).toContain("<b>23 steps</b> on Fri, Oct 16 · latest day, may be incomplete");
  });

  test("stale data does not create a current trend and offers a source check", () => {
    const html = renderToStaticMarkup(
      <TodayTrend options={[option]} now="2026-12-01T00:00:00Z" />,
    );
    expect(html).toContain("No readings in this window");
    expect(html).toContain("Last reading Oct 16.");
    expect(html).toContain('href="/sources"');
    expect(html).not.toContain('role="img"');
    expect(html).not.toContain('role="slider"');
    expect(html).not.toContain("Daily values");
  });

  test("a digest row links to its exact finding, including legacy evidence", () => {
    const finding: Finding = {
      id: 314,
      finding_type: "trend",
      metric: "activity.steps",
      severity: null,
      structured_data: {},
      created_at: "2026-10-16T00:00:00Z",
      card: null,
      schema_version: 0,
    };
    const html = renderToStaticMarkup(<TodayFindings findings={[finding]} />);
    expect(html).toContain('href="/findings?finding=314#selected-finding"');
    expect(html).toContain("View evidence");
  });
});
