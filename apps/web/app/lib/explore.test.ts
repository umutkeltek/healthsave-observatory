import { describe, expect, it } from "bun:test";

import {
  deserializeExploreState,
  encodeExploreState,
  encodePanels,
  fetchRange,
  filterWindow,
  normalize,
  parseExploreState,
  parsePanels,
  parseSavedViews,
  type ExplorePanel,
} from "./explore";

describe("explore panel encoding", () => {
  it("round-trips panels through encode/parse", () => {
    const panels: ExplorePanel[] = [
      { chart: "line", metrics: ["vital.hrv_sdnn", "vital.resting_heart_rate"] },
      { chart: "heatmap", metrics: ["vital.heart_rate"] },
    ];
    expect(parsePanels(encodePanels(panels))).toEqual(panels);
  });

  it("falls back to defaults when there is no panels param, or only garbage", () => {
    expect(parsePanels(undefined).length).toBeGreaterThan(0);
    // a segment with no metrics is dropped, not kept as an empty panel
    expect(parsePanels("line:").length).toBeGreaterThan(0);
  });

  it("bounds URL-driven work and drops invalid metric ids", () => {
    const raw = Array.from({ length: 12 }, (_, index) =>
      `line:vital.metric_${index},activity.steps,mobility.walking_speed,vital.hrv_sdnn,extra.metric`,
    ).join(";");
    const panels = parsePanels(raw);
    expect(panels).toHaveLength(8);
    expect(panels.every((panel) => panel.metrics.length === 4)).toBe(true);
    expect(parsePanels("line:not-a-metric")[0].metrics).not.toContain("not-a-metric");
  });

  it("coerces an unknown chart kind to line", () => {
    expect(parsePanels("bogus:vital.hrv_sdnn")[0].chart).toBe("line");
  });
});

describe("explore state parsing", () => {
  it("applies safe defaults for missing/invalid fields", () => {
    const s = parseExploreState({});
    expect(s.range).toBe("30d");
    expect(s.grain).toBe("day");
    expect(s.stat).toBe("mean");
  });

  it("rejects out-of-range values", () => {
    const s = parseExploreState({ range: "5y", grain: "decade", stat: "median" });
    expect(s.range).toBe("30d");
    expect(s.grain).toBe("day");
    expect(s.stat).toBe("mean");
  });

  it("keeps valid values and round-trips through encodeExploreState", () => {
    const s = parseExploreState({
      range: "90d",
      grain: "week",
      stat: "max",
      panels: "line:vital.hrv_sdnn",
    });
    expect(s.range).toBe("90d");
    expect(s.grain).toBe("week");
    expect(s.stat).toBe("max");
    // encode → parse is stable
    const qs = new URLSearchParams(encodeExploreState(s));
    expect(parseExploreState(Object.fromEntries(qs))).toEqual(s);
  });
});

describe("custom date window", () => {
  it("parses valid YYYY-MM-DD from/to and rejects junk", () => {
    const ok = parseExploreState({ from: "2026-06-01", to: "2026-06-20" });
    expect(ok.from).toBe("2026-06-01");
    expect(ok.to).toBe("2026-06-20");
    const junk = parseExploreState({ from: "june", to: "2026/06/20" });
    expect(junk.from).toBeUndefined();
    expect(junk.to).toBeUndefined();
  });

  it("round-trips from/to through encode", () => {
    const s = parseExploreState({ from: "2026-06-01", to: "2026-06-20", panels: "line:m" });
    const qs = new URLSearchParams(encodeExploreState(s));
    expect(parseExploreState(Object.fromEntries(qs))).toEqual(s);
  });

  it("fetchRange pulls the widest preset when a window is set, else the preset", () => {
    expect(fetchRange(parseExploreState({ range: "7d" }))).toBe("7d");
    expect(fetchRange(parseExploreState({ range: "7d", from: "2026-06-01" }))).toBe("all");
  });

  it("filterWindow slices inclusively and passes through with no bounds", () => {
    const pts = [{ t: "2026-05-31T12:00:00Z" }, { t: "2026-06-10T12:00:00Z" }, { t: "2026-06-21T12:00:00Z" }];
    expect(filterWindow(pts, "2026-06-01", "2026-06-20")).toEqual([{ t: "2026-06-10T12:00:00Z" }]);
    expect(filterWindow(pts, undefined, undefined)).toEqual(pts);
    // an open upper bound keeps everything from `from` onward
    expect(filterWindow(pts, "2026-06-01", undefined).length).toBe(2);
  });
});

describe("normalize", () => {
  it("maps to 0..1", () => {
    expect(normalize([0, 5, 10])).toEqual([0, 0.5, 1]);
  });
  it("maps a flat series to 0.5", () => {
    expect(normalize([4, 4, 4])).toEqual([0.5, 0.5, 0.5]);
  });
  it("handles the empty series", () => {
    expect(normalize([])).toEqual([]);
  });
});

// The bug (audit web #18): removing the last panel wrote "panels=" to the
// URL, which parsed as "no param" and brought back the five default panels.
describe("removing every panel", () => {
  it("an explicitly empty panel list stays empty", () => {
    expect(parsePanels("")).toEqual([]);
    const emptied = parseExploreState({ panels: "" });
    expect(emptied.panels).toEqual([]);
    expect(deserializeExploreState(encodeExploreState(emptied))?.panels).toEqual([]);
  });

  it("no panels param at all is the curated default dashboard", () => {
    expect(parseExploreState({}).panels.length).toBeGreaterThan(0);
  });
});

// The bug (audit web #18): saved views were JSON.parse'd from localStorage and
// used as-is; one malformed entry broke the Explore controls.
describe("saved views from storage", () => {
  it("keeps only well-formed views", () => {
    const raw = JSON.stringify([
      { name: "Recovery", qs: "range=30d" },
      { name: "", qs: "range=7d" },
      { name: "No query" },
      "junk",
      null,
      { name: "Sleep", qs: "range=90d", extra: true },
    ]);
    expect(parseSavedViews(raw)).toEqual([
      { name: "Recovery", qs: "range=30d" },
      { name: "Sleep", qs: "range=90d" },
    ]);
  });

  it("anything that is not a list of views is no views", () => {
    expect(parseSavedViews(null)).toEqual([]);
    expect(parseSavedViews("not json")).toEqual([]);
    expect(parseSavedViews('{"name":"x","qs":"y"}')).toEqual([]);
  });

  it("duplicate names keep the last one", () => {
    const views = parseSavedViews(
      JSON.stringify([
        { name: "A", qs: "n=1" },
        { name: "B", qs: "n=2" },
        { name: "A", qs: "n=3" },
      ]),
    );
    expect(views).toEqual([
      { name: "B", qs: "n=2" },
      { name: "A", qs: "n=3" },
    ]);
  });
});
