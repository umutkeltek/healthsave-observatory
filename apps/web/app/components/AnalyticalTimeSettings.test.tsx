import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { AnalyticalTimeSettingsForm } from "./AnalyticalTimeSettings";
import type { AnalyticalTimeSettings } from "../lib/api";

const BASE_SETTINGS: AnalyticalTimeSettings = {
  time_zone: "Europe/Istanbul",
  day_boundary_minutes: 240,
  day_boundary: "04:00",
  revision: 1,
  sleep_day_assignment: "wake_time",
};

describe("AnalyticalTimeSettingsForm", () => {
  test("renders the common IANA time zones in the dropdown", () => {
    const html = renderToStaticMarkup(<AnalyticalTimeSettingsForm initial={BASE_SETTINGS} />);
    for (const zone of [
      "UTC",
      "Europe/Istanbul",
      "Europe/London",
      "America/New_York",
      "Asia/Tokyo",
    ]) {
      expect(html).toContain(zone);
    }
  });

  test("preserves an unknown time zone by prepending it to the dropdown", () => {
    const custom = { ...BASE_SETTINGS, time_zone: "Asia/Kolkata" };
    const html = renderToStaticMarkup(<AnalyticalTimeSettingsForm initial={custom} />);
    // The custom zone should appear as the first option (selected).
    const match = html.match(/<option[^>]*value="Asia\/Kolkata"[^>]*selected[^>]*>Asia\/Kolkata<\/option>/);
    expect(match).not.toBeNull();
  });

  test("offers the canonical day-boundary presets (00:00 → 12:00)", () => {
    const html = renderToStaticMarkup(<AnalyticalTimeSettingsForm initial={BASE_SETTINGS} />);
    for (const label of ["00:00", "02:00", "04:00", "06:00", "12:00"]) {
      expect(html).toContain(label);
    }
  });

  test("current basis line shows the saved time zone and boundary", () => {
    const html = renderToStaticMarkup(<AnalyticalTimeSettingsForm initial={BASE_SETTINGS} />);
    expect(html).toContain("Current basis:");
    expect(html).toContain("Europe/Istanbul");
    expect(html).toContain("04:00");
  });

  test("save button reads 'Save time basis' when idle", () => {
    const html = renderToStaticMarkup(<AnalyticalTimeSettingsForm initial={BASE_SETTINGS} />);
    expect(html).toContain("Save time basis");
  });
});
