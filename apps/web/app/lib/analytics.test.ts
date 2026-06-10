import { describe, expect, it } from "bun:test";

import {
  bucketBy,
  classify,
  dayOfWeekPivot,
  detectDivergence,
  distribution,
  groupBySource,
  groupByStream,
  hrZoneHistogram,
  periodSplit,
  topN,
  weekHourPivot,
} from "./analytics";
import type { SeriesPoint } from "./api";

function pt(
  t: string,
  value: number | null,
  source_id = "apple",
  stream_id: string | null = null,
): SeriesPoint {
  return { t, value, code: null, unit: "count", source_id, stream_id, confidence: null };
}

describe("groupBySource", () => {
  it("keys strictly on source_id and drops nothing", () => {
    const pts = [pt("2026-06-01T00:00:00Z", 60, "apple"), pt("2026-06-01T01:00:00Z", 62, "whoop"), pt("2026-06-01T02:00:00Z", 61, "apple")];
    const g = groupBySource(pts);
    expect(g.size).toBe(2);
    expect(g.get("apple")?.length).toBe(2);
    expect(g.get("whoop")?.length).toBe(1);
  });
  it("handles empty input", () => {
    expect(groupBySource([]).size).toBe(0);
  });
});

describe("groupByStream", () => {
  it("groups by stream_id and drops null-stream points", () => {
    const pts = [
      pt("t1", 1, "apple", "watch"),
      pt("t2", 2, "apple", "phone"),
      pt("t3", 3, "apple", "watch"),
      pt("t4", 4, "apple", null),
    ];
    const g = groupByStream(pts);
    expect(g.size).toBe(2);
    expect(g.get("watch")?.length).toBe(2);
    expect(g.get("phone")?.length).toBe(1);
  });
});

describe("distribution / topN", () => {
  it("counts per source, sorted desc", () => {
    const pts = [pt("t1", 1, "a"), pt("t2", 1, "a"), pt("t3", 1, "b")];
    const d = distribution(pts);
    expect(d).toEqual([{ source_id: "a", count: 2 }, { source_id: "b", count: 1 }]);
    expect(topN(pts, 1)).toEqual([{ source_id: "a", count: 2 }]);
  });
  it("counts null-valued points too (presence, not value)", () => {
    expect(distribution([pt("t", null, "a")])).toEqual([{ source_id: "a", count: 1 }]);
  });
});

describe("bucketBy", () => {
  it("buckets by day with the chosen stat and drops nulls", () => {
    const pts = [
      pt("2026-06-01T08:00:00Z", 10),
      pt("2026-06-01T20:00:00Z", 20),
      pt("2026-06-01T21:00:00Z", null),
      pt("2026-06-02T08:00:00Z", 30),
    ];
    const day = bucketBy(pts, "day", "mean");
    expect(day).toEqual([
      { t: "2026-06-01", value: 15, n: 2 },
      { t: "2026-06-02", value: 30, n: 1 },
    ]);
    expect(bucketBy(pts, "day", "sum")[0].value).toBe(30);
    expect(bucketBy(pts, "day", "max")[0].value).toBe(20);
  });
  it("buckets by hour and week deterministically (UTC)", () => {
    const pts = [pt("2026-06-03T08:15:00Z", 5), pt("2026-06-03T08:45:00Z", 7)];
    expect(bucketBy(pts, "hour", "mean")).toEqual([{ t: "2026-06-03T08", value: 6, n: 2 }]);
    // 2026-06-03 is a Wednesday → week anchors to Monday 2026-06-01.
    expect(bucketBy(pts, "week", "mean")[0].t).toBe("2026-06-01");
  });
  it("returns [] for empty input", () => {
    expect(bucketBy([], "day", "mean")).toEqual([]);
  });
});

describe("hrZoneHistogram", () => {
  it("bins bpm into the five zones", () => {
    const pts = [pt("t", 60), pt("t", 120), pt("t", 200), pt("t", null)];
    const h = hrZoneHistogram(pts);
    expect(h.find((z) => z.zone === "Z1")?.count).toBe(1); // 60
    expect(h.find((z) => z.zone === "Z2")?.count).toBe(1); // 120
    expect(h.find((z) => z.zone === "Z5")?.count).toBe(1); // 200
    expect(h.reduce((s, z) => s + z.count, 0)).toBe(3); // null excluded
  });
});

describe("dayOfWeekPivot", () => {
  it("indexes 0=Mon..6=Sun in UTC", () => {
    // 2026-06-01 is a Monday.
    const cells = dayOfWeekPivot([pt("2026-06-01T12:00:00Z", 100)]);
    expect(cells[0]).toEqual({ dow: 0, label: "Mon", value: 100, n: 1 });
    expect(cells[6].n).toBe(0);
  });
});

describe("weekHourPivot", () => {
  it("returns a 7×24 grid with stats in the right cells (UTC)", () => {
    // 2026-06-01 is a Monday; 08:00 UTC.
    const cells = weekHourPivot([pt("2026-06-01T08:00:00Z", 10), pt("2026-06-01T08:30:00Z", 20)]);
    expect(cells.length).toBe(7 * 24);
    const mon8 = cells.find((c) => c.dow === 0 && c.hour === 8);
    expect(mon8).toEqual({ dow: 0, hour: 8, value: 15, n: 2 });
    const empty = cells.find((c) => c.dow === 3 && c.hour === 3);
    expect(empty?.value).toBeNull();
  });
});

describe("periodSplit", () => {
  it("returns A, B and a delta — never a merged value", () => {
    const pts = [
      pt("2026-06-01T00:00:00Z", 10),
      pt("2026-06-02T00:00:00Z", 10),
      pt("2026-06-03T00:00:00Z", 20),
      pt("2026-06-04T00:00:00Z", 20),
    ];
    const s = periodSplit(pts);
    expect(s.a.mean).toBe(10);
    expect(s.b.mean).toBe(20);
    expect(s.delta.abs).toBe(10);
    expect(s.delta.pct).toBe(100);
    expect(s.delta.direction).toBe("up");
    // no top-level "value"/"merged" field exists — comparison stays A/B
    expect(Object.keys(s).sort()).toEqual(["a", "b", "delta"]);
  });
  it("guards divide-by-zero when A mean is 0", () => {
    const s = periodSplit([pt("2026-06-01T00:00:00Z", 0), pt("2026-06-02T00:00:00Z", 5)]);
    expect(s.delta.pct).toBeNull();
  });
  it("handles empty input", () => {
    const s = periodSplit([]);
    expect(s.a.n).toBe(0);
    expect(s.b.n).toBe(0);
    expect(s.delta.direction).toBe("flat");
  });
});

describe("classify (threshold bands)", () => {
  it("classifies against the ported Grafana bands", () => {
    expect(classify("vital.resting_heart_rate", 55)?.label).toBe("typical");
    expect(classify("vital.resting_heart_rate", 90)?.tone).toBe("down");
    expect(classify("vital.blood_oxygen", 92)?.tone).toBe("down");
    expect(classify("unknown.metric", 5)).toBeNull();
  });
});

describe("detectDivergence", () => {
  const mk = (source: string, values: number[]) =>
    values.map((value, i) => ({
      t: `2026-06-0${(i % 7) + 1}T08:00:00Z`,
      value,
      code: null,
      unit: "ms",
      source_id: source,
      stream_id: null,
      confidence: null,
    }));

  it("reports no divergence for a single source", () => {
    const result = detectDivergence(mk("apple", [50, 52, 54]));
    expect(result.diverged).toBe(false);
    expect(result.gapPct).toBeNull();
  });

  it("quantifies the gap between disagreeing sources", () => {
    const result = detectDivergence([...mk("apple", [50, 50, 50]), ...mk("whoop", [60, 60, 60])]);
    expect(result.diverged).toBe(true);
    expect(result.gapPct).toBeCloseTo((10 / 55) * 100, 0);
    expect(result.sources.sort()).toEqual(["apple", "whoop"]);
  });

  it("agrees within threshold → not diverged", () => {
    const result = detectDivergence([...mk("apple", [50, 50, 50]), ...mk("whoop", [51, 51, 51])]);
    expect(result.diverged).toBe(false);
  });

  it("ignores sources with too few points", () => {
    const result = detectDivergence([...mk("apple", [50, 50, 50]), ...mk("whoop", [90])]);
    expect(result.diverged).toBe(false);
  });
});
