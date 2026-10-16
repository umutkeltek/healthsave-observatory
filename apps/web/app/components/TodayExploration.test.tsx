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

  test("daily totals explain partial days and expose dates and values outside chart hover", () => {
    const html = renderToStaticMarkup(
      <TodayTrend options={[option]} now="2026-10-16T23:00:00Z" />,
    );
    expect(html).toContain("Latest day may be incomplete");
    expect(html).toContain("2 of 30 days recorded");
    expect(html).toContain("Daily totals across sources");
    expect(html).toContain("Dates in UTC");
    expect(html).toContain("View 2 daily values");
    expect(html).toContain('<time dateTime="2026-10-16">');
    expect(html).toContain("23 steps");
    expect(html).toContain('href="/library/activity.steps?range=30d"');
  });

  test("stale data does not create a current trend and offers a source check", () => {
    const html = renderToStaticMarkup(
      <TodayTrend options={[option]} now="2026-12-01T00:00:00Z" />,
    );
    expect(html).toContain("No readings in this window");
    expect(html).toContain('href="/sources"');
    expect(html).not.toContain("<svg");
    expect(html).not.toContain("View 2 daily values");
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
