import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { AnalyticalTimeSettingsForm, TimeBasisStatus, TimeBasisSummary } from "./AnalyticalTimeSettings";
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

describe("TimeBasisSummary", () => {
  // The bug: "Current basis" printed the form's draft, so an unsaved (or
  // failed) change read as the basis the analyses use.
  test("the current basis is the saved one; a different draft is marked unsaved", () => {
    const html = renderToStaticMarkup(
      <TimeBasisSummary saved={BASE_SETTINGS} draft={{ time_zone: "UTC", day_boundary_minutes: 0 }} />,
    );
    expect(html).toContain("Current basis: Europe/Istanbul · day boundary 04:00");
    expect(html).toContain("Not saved yet: UTC · day boundary 00:00");
  });

  test("a draft equal to the saved basis shows no unsaved line", () => {
    const html = renderToStaticMarkup(
      <TimeBasisSummary saved={BASE_SETTINGS} draft={{ time_zone: "Europe/Istanbul", day_boundary_minutes: 240 }} />,
    );
    expect(html).toContain("Current basis: Europe/Istanbul · day boundary 04:00");
    expect(html).not.toContain("Not saved yet");
  });
});

describe("TimeBasisStatus", () => {
  test("a failed save renders as an error whatever its wording", () => {
    const html = renderToStaticMarkup(<TimeBasisStatus status={{ kind: "error", message: "Saved state unknown" }} />);
    expect(html).toContain("exp-error");
  });
});
