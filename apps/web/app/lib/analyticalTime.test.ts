import { describe, expect, test } from "bun:test";

import { analyticalDayKey, analyticalDayOfWeek, analyticalWeekKey, localHour } from "./analyticalTime";

const ISTANBUL = { time_zone: "Europe/Istanbul", day_boundary_minutes: 240 };

describe("person-local analytical time", () => {
  test("keeps readings before 04:00 local on the previous physiological day", () => {
    expect(analyticalDayKey("2026-07-10T00:30:00Z", ISTANBUL)).toBe("2026-07-09");
    expect(analyticalDayKey("2026-07-10T01:30:00Z", ISTANBUL)).toBe("2026-07-10");
  });

  test("uses the selected timezone for local hour", () => {
    expect(localHour("2026-07-10T00:30:00Z", ISTANBUL)).toBe(3);
    expect(localHour("2026-07-10T00:30:00Z", { time_zone: "America/New_York", day_boundary_minutes: 240 })).toBe(20);
  });

  test("derives weekday and week from the shifted analytical day", () => {
    const day = analyticalDayKey("2026-07-13T01:00:00Z", ISTANBUL);
    expect(day).toBe("2026-07-13");
    expect(analyticalDayOfWeek(day!)).toBe(0);
    expect(analyticalWeekKey(day!)).toBe("2026-07-13");
  });
});
