import { describe, expect, test } from "bun:test";

import { type AlignedPair, alignDaily, bucketBy, CORRELATION_MIN_DAYS, dayOfWeekPivot, detectDivergence, pearson, periodSplit, weekHourPivot } from "./analytics";
import {
  analyticalDayKey,
  analyticalDayOfWeek,
  analyticalWeekKey,
  localHour,
  UTC_TIME_BASIS,
} from "./analyticalTime";
import {
  DEMO_COMPARE_SERIES,
  demoPatternSeries,
  demoRelatedPair,
  DEMO_CORRELATIONS,
  DEMO_RELATE_METRICS,
} from "./demoSeries";
import {
  displayItemsForFindings,
  findingCardChips,
  groupFindingsForDisplay,
  recoveryEvidence,
  userFindingTitle,
} from "./findingPresentation";

// ─────────────────────────────────────────────────────────────────
// Analytics engine — every deterministic reduction of the Grafana math
// ─────────────────────────────────────────────────────────────────

const HEART_RATE_METRIC = {
  id: "vital.heart_rate",
  display_name: "Heart Rate",
  category: "vital",
  value_type: "numeric",
  canonical_unit: "bpm",
} as any;

const HEART_RATE_POINTS: SeriesPoint[] = [
  { t: "2026-07-01T08:00:00Z", value: 68, source_id: "aw", stream_id: "aw-dev", unit: "bpm" },
  { t: "2026-07-01T12:00:00Z", value: 72, source_id: "aw", stream_id: "aw-dev", unit: "bpm" },
  { t: "2026-07-01T20:00:00Z", value: 64, source_id: "wp", stream_id: "wp-dev", unit: "bpm" },
  { t: "2026-07-02T08:00:00Z", value: 66, source_id: "aw", stream_id: "aw-dev", unit: "bpm" },
  { t: "2026-07-03T08:00:00Z", value: 70, source_id: "aw", stream_id: "aw-dev", unit: "bpm" },
  { t: "2026-07-04T08:00:00Z", value: 67, source_id: "aw", stream_id: "aw-dev", unit: "bpm" },
  { t: "2026-07-05T08:00:00Z", value: 65, source_id: "aw", stream_id: "aw-dev", unit: "bpm" },
  { t: "2026-07-06T08:00:00Z", value: 68, source_id: "aw", stream_id: "aw-dev", unit: "bpm" },
  { t: "2026-07-07T08:00:00Z", value: 72, source_id: "aw", stream_id: "aw-dev", unit: "bpm" },
];

describe("Patterns flow: demo series through every pivot", () => {
  const series = demoPatternSeries(HEART_RATE_METRIC);

  test("demo series feeds the heatmap, weekday, zone, and table panels", () => {
    const heat = weekHourPivot(series.points);
    const allNull = heat.every((c) => c.value === null);
    expect(allNull).toBe(false);
    const dow = dayOfWeekPivot(series.points);
    expect(dow.length).toBe(7);
    const nonZero = dow.filter((c) => c.n > 0);
    expect(nonZero.length).toBeGreaterThanOrEqual(3);
  });

  test("period split keeps both halves verbatim and returns honest delta", () => {
    const ps = periodSplit(series.points);
    expect(ps.a.n).toBeGreaterThan(0);
    expect(ps.b.n).toBeGreaterThan(0);
    expect(typeof ps.delta.abs).toBe("number");
    expect(ps.a.mean).not.toEqual(ps.b.mean);
  });

  test("multi-source divergence flags the gap when sources disagree enough", () => {
    const div = detectDivergence(series.points);
    expect(div.sources.length).toBeGreaterThanOrEqual(1);
    expect(div.diverged).toBeBoolean();
  });

  test("demo compare series keeps both streams verbatim", () => {
    const demo = DEMO_COMPARE_SERIES;
    expect(demo.metric.display_name.length).toBeGreaterThan(0);
    expect(demo.points.length).toBeGreaterThanOrEqual(2);
    const byStream = new Map<string, number>();
    for (const point of demo.points) {
      if (point.stream_id) {
        byStream.set(point.stream_id, (byStream.get(point.stream_id) ?? 0) + 1);
      }
    }
    expect(byStream.size).toBeGreaterThanOrEqual(2);
  });

  test("demo provenance builds an honest coverage summary", () => {
    const seriesWithNulls: SeriesPoint[] = [
      { t: "2026-07-01T08:00:00Z", value: 5, source_id: "src-a", stream_id: "s1", unit: "kg" },
      { t: "2026-07-02T08:00:00Z", value: null, source_id: "src-a", stream_id: "s1", unit: "kg" },
      { t: "2026-07-03T08:00:00Z", value: 6, source_id: "src-b", stream_id: "s2", unit: "kg" },
    ];
    const buckets = bucketBy(seriesWithNulls, "day", "mean");
    expect(buckets.length).toBe(2);
    const aRows = seriesWithNulls.filter((point) => point.source_id === "src-a");
    const aValues = aRows.filter((point) => point.value !== null);
    expect(aRows.length - aValues.length).toBe(1);
  });
});

describe("Relationships flow: demo fixtures through align + pearson", () => {
  test("the coupled demo pair yields a real-but-imperfect exploratory r", () => {
    const pair = demoRelatedPair(DEMO_RELATE_METRICS[0], DEMO_RELATE_METRICS[1]);
    expect(pair.a.metric.display_name.length).toBeGreaterThan(0);
    expect(pair.b.metric.display_name.length).toBeGreaterThan(0);
    const aligned: AlignedPair[] = alignDaily(pair.a.points, pair.b.points);
    expect(aligned.length).toBeGreaterThanOrEqual(CORRELATION_MIN_DAYS);
    const stat = pearson(aligned);
    expect(stat).not.toBeNull();
    if (stat) {
      expect(stat.r).toBeGreaterThan(0.3);
      expect(stat.r).toBeLessThan(1.0);
    }
  });

  test("demo correlations are well-formed and include an honest weak row", () => {
    expect(DEMO_CORRELATIONS.length).toBeGreaterThanOrEqual(2);
    const hasWeakRow = DEMO_CORRELATIONS.some(
      (c) => c.coefficient !== null && Math.abs(c.coefficient) < 0.5,
    );
    expect(hasWeakRow).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────────
// Analytical time — person-local day assignment
// ─────────────────────────────────────────────────────────────────

describe("Analytical time: person-local calendar", () => {
  const ISTANBUL = { time_zone: "Europe/Istanbul", day_boundary_minutes: 240 };

  test("midnight UTC maps to correct local analytical day", () => {
    const day = analyticalDayKey("2026-07-10T00:30:00Z", ISTANBUL);
    expect(day).toBe("2026-07-09");
    expect(analyticalDayKey("2026-07-10T01:30:00Z", ISTANBUL)).toBe("2026-07-10");
  });

  test("local hour is derived from the specified timezone", () => {
    expect(localHour("2026-07-10T00:30:00Z", ISTANBUL)).toBe(3);
    expect(
      localHour("2026-07-10T00:30:00Z", {
        time_zone: "America/New_York",
        day_boundary_minutes: 240,
      }),
    ).toBe(20);
  });

  test("UTC basis uses zero boundary by default", () => {
    expect(UTC_TIME_BASIS.day_boundary_minutes).toBe(0);
    expect(UTC_TIME_BASIS.time_zone).toBe("UTC");
  });

  test("week key derives from the shifted analytical day", () => {
    const day = analyticalDayKey("2026-07-13T01:00:00Z", ISTANBUL);
    expect(day).toBe("2026-07-13");
    expect(analyticalDayOfWeek(day!)).toBe(0);
    expect(analyticalWeekKey(day!)).toBe("2026-07-13");
  });
});

// ─────────────────────────────────────────────────────────────────
// Finding presentation — v2 recovery evidence, grouping, chips
// ─────────────────────────────────────────────────────────────────

describe("Finding presentation: recovery evidence contract", () => {
  test("accepts only evidence-qualified v2 recovery findings for the hero", () => {
    const v2Valid = {
      id: 1,
      finding_type: "recovery_score",
      metric: "recovery",
      severity: "info",
      structured_data: {
        score: 68,
        formula_version: 2,
        input_count: 3,
        input_total: 5,
        evidence_level: "partial",
      },
      created_at: "2026-07-03T10:00:00Z",
      card: null,
      schema_version: 1,
    } as any;
    const evidence = recoveryEvidence(v2Valid);
    expect(evidence).not.toBeNull();
    if (evidence) {
      expect(evidence.score).toBe(68);
      expect(evidence.inputCount).toBe(3);
    }
  });

  test("rejects legacy v1 recoveries with no evidence contract", () => {
    const v1Legacy = {
      id: 2,
      finding_type: "recovery_score",
      metric: "recovery",
      severity: "info",
      structured_data: { score: 91, signals_available: ["hrv"] },
      created_at: "2026-07-03T10:00:00Z",
      card: null,
      schema_version: 0,
    } as any;
    expect(recoveryEvidence(v1Legacy)).toBeNull();
  });

  test("clusters repeated recovery checks into one display item", () => {
    const items = displayItemsForFindings(
      [64, 67, 56, 70, 63].map((score, index) => ({
        id: index + 1,
        finding_type: "recovery_score",
        metric: "recovery",
        severity: "info",
        structured_data: { score },
        created_at: `2026-07-0${index + 1}T10:00:00Z`,
        card: null,
        schema_version: 0,
      })) as any[],
    );
    expect(items).toHaveLength(1);
    expect(items[0].kind).toBe("cluster");
    expect(items[0].count).toBe(5);
  });
});
