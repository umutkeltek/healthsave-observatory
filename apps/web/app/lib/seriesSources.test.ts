import { describe, expect, test } from "bun:test";
import type { SeriesPoint } from "./api";
import { sourceGroupLabel, splitBySource } from "./series";

const APPLE = { source_id: "apple", stream_id: "watch-stream" };
const WHOOP = { source_id: "whoop", stream_id: "whoop-stream" };

function p(value: number | null, t: string, src = APPLE, extra: Partial<SeriesPoint> = {}): SeriesPoint {
  return { value, t, code: null, unit: "bpm", confidence: null, ...src, ...extra };
}

describe("splitBySource: two devices are two readings", () => {
  // The same two mornings from an Apple Watch (60) and a Whoop (50).
  const points = [
    p(60, "2026-11-20T06:00:00Z"),
    p(50, "2026-11-20T06:05:00Z", WHOOP),
    p(61, "2026-11-21T06:00:00Z"),
    p(51, "2026-11-21T06:20:00Z", WHOOP),
    p(null, "2026-11-22T06:00:00Z"),
  ];

  test("one group per device, newest reading first, values never pooled", () => {
    const groups = splitBySource(points);
    expect(groups.map((g) => g.sourceId)).toEqual(["whoop", "apple"]);
    expect(groups[0].points.map((x) => x.value)).toEqual([50, 51]);
    expect(groups[1].points.map((x) => x.value)).toEqual([60, 61]);
    expect(groups[1].latest.value).toBe(61);
    // No group holds both devices' readings (no 55 can ever be drawn).
    for (const group of groups) expect(new Set(group.points.map((x) => x.source_id)).size).toBe(1);
  });

  test("one device stays one group", () => {
    expect(splitBySource(points.filter((x) => x.source_id === "apple"))).toHaveLength(1);
  });

  test("labels come from the stream, then the source, never a bare id", () => {
    const [whoop, apple] = splitBySource(points);
    const labels = { "whoop-stream": "Whoop", apple: "Apple Health" };
    expect(sourceGroupLabel(whoop, labels, 0)).toBe("Whoop");
    expect(sourceGroupLabel(apple, labels, 1)).toBe("Apple Health");
    expect(sourceGroupLabel(apple, {}, 1)).toBe("Source 2");
  });
});
