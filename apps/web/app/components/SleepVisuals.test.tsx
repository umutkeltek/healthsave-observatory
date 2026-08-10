import { describe, expect, it } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { Hypnogram, SleepStatBox, StageBreakdown } from "./SleepVisuals";
import type { SleepNight } from "../lib/sleep";

describe("Hypnogram", () => {
  it("renders recorded intervals with widths proportional to their duration", () => {
    const html = renderToStaticMarkup(
      <Hypnogram
        segments={[
          {
            t: "2026-06-01T22:00:00Z",
            end: "2026-06-01T22:30:00Z",
            durationMin: 30,
            stage: "deep",
          },
          {
            t: "2026-06-01T22:30:00Z",
            end: "2026-06-02T00:00:00Z",
            durationMin: 90,
            stage: "core",
          },
        ]}
      />,
    );

    expect(html).toContain("flex-grow:30");
    expect(html).toContain("flex-grow:90");
    expect(html).toContain("→");
    expect(html).toMatch(
      /aria-label="Sleep stage sequence: Deep · \d{2}:\d{2} → \d{2}:\d{2}; Core · \d{2}:\d{2} → \d{2}:\d{2}"/,
    );
  });

  it("labels shared light and in-bed states explicitly", () => {
    const html = renderToStaticMarkup(
      <Hypnogram
        segments={[
          { t: "2026-06-01T22:00:00Z", durationMin: 30, stage: "light" },
          { t: "2026-06-01T22:30:00Z", durationMin: 30, stage: "in_bed" },
        ]}
      />,
    );

    expect(html).toContain("Light ·");
    expect(html).toContain("In Bed ·");
  });
});

describe("StageBreakdown", () => {
  it("states how intervals from multiple streams are reconciled", () => {
    const night: SleepNight = {
      date: "2026-06-01",
      bedtime: "2026-06-01T22:00:00Z",
      wakeTime: "2026-06-02T06:00:00Z",
      durationMin: 480,
      stageMinutes: { core: 480 },
      segments: [],
      streamCount: 2,
    };

    const html = renderToStaticMarkup(<StageBreakdown night={night} />);
    expect(html).toContain("2 source streams contributed");
    expect(html).toContain("overlapping clock time is counted once");
    expect(html).not.toContain("de-duplicated");
  });

  it("preserves percentages for static nights whose duration already includes awake time", () => {
    const night: SleepNight = {
      date: "2026-06-01",
      bedtime: "2026-06-01T22:00:00Z",
      wakeTime: "2026-06-02T06:00:00Z",
      durationMin: 480,
      stageMinutes: { core: 420, awake: 60 },
      segments: [],
    };

    const html = renderToStaticMarkup(<StageBreakdown night={night} />);
    expect(html).toContain("420m <span class=\"sleep-breakdown-pct\">88%</span>");
    expect(html).toContain("60m <span class=\"sleep-breakdown-pct\">13%</span>");
  });

  it("renders shared sleep states against tracked time and excludes contextual states", () => {
    const night: SleepNight = {
      date: "2026-06-01",
      bedtime: "2026-06-01T22:00:00Z",
      wakeTime: "2026-06-02T01:00:00Z",
      durationMin: 120,
      trackedMin: 120,
      stageMinutes: { deep: 30, light: 60, asleep: 30, in_bed: 180, unknown: 5 },
      segments: [],
    };

    const html = renderToStaticMarkup(<StageBreakdown night={night} />);
    expect(html).toContain("Deep");
    expect(html).toContain("Light");
    expect(html).toContain("Asleep (stage unspecified)");
    expect(html).toContain("30m <span class=\"sleep-breakdown-pct\">25%</span>");
    expect(html).toContain("60m <span class=\"sleep-breakdown-pct\">50%</span>");
    expect(html).toContain("In Bed 180m");
    expect(html).toContain("Unknown 5m");
    expect(html).toContain("excluded from sleep duration");
  });

  it("shows conflicting stage time instead of double-counting it", () => {
    const night: SleepNight = {
      date: "2026-06-01",
      bedtime: "2026-06-01T22:00:00Z",
      wakeTime: "2026-06-01T23:00:00Z",
      durationMin: 60,
      trackedMin: 60,
      stageMinutes: { conflict: 30, core: 30 },
      segments: [],
      streamCount: 2,
    };

    const html = renderToStaticMarkup(<StageBreakdown night={night} />);
    expect(html).toContain("Conflicting stages");
    expect(html).toContain("30m <span class=\"sleep-breakdown-pct\">50%</span>");
    expect(html).toContain("30m had conflicting stage labels");
  });
});

describe("SleepStatBox", () => {
  it("carries rounded minutes into the hour", () => {
    const html = renderToStaticMarkup(
      <SleepStatBox
        bedtime="2026-06-01T22:00:00Z"
        wakeTime="2026-06-02T06:00:00Z"
        durationMin={479.6}
      />,
    );

    expect(html).toContain("<h1>8h 0m</h1>");
  });
});
