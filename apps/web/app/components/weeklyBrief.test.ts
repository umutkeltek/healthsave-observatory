import { describe, expect, test } from "bun:test";

import type { InsightsLatest, Narrative } from "../lib/api";
import type { TriggerAnalysisResult } from "../lib/actions";
import { needsDailyFallback, refreshNote } from "./RefreshInsightsButton";
import { pickBrief } from "./WeeklyBriefCard";

const NOW = Date.parse("2026-11-08T12:00:00Z");
const daysAgo = (days: number) => new Date(NOW - days * 86_400_000).toISOString();

function narrative(type: "weekly_summary" | "daily_briefing", createdAt: string | null): Narrative {
  return { insight_type: type, narrative: `${type} text`, created_at: createdAt } as Narrative;
}

function latest(weekly: Narrative | null, daily: Narrative | null): InsightsLatest {
  return { weekly_summary: weekly, daily_briefing: daily, runs: { weekly_summary: null, daily_briefing: null } };
}

describe("which brief the card shows", () => {
  // The bug: weekly ?? daily kept showing a weekly from weeks ago over
  // today's briefing.
  test("a weekly older than its window gives way to a newer daily briefing", () => {
    const daily = narrative("daily_briefing", daysAgo(0.2));
    expect(pickBrief(latest(narrative("weekly_summary", daysAgo(30)), daily), NOW)).toBe(daily);
  });

  test("a current weekly is still preferred over a newer daily", () => {
    const weekly = narrative("weekly_summary", daysAgo(2));
    expect(pickBrief(latest(weekly, narrative("daily_briefing", daysAgo(0.1))), NOW)).toBe(weekly);
  });

  test("with only one brief, that one is shown, however old", () => {
    const weekly = narrative("weekly_summary", daysAgo(30));
    expect(pickBrief(latest(weekly, null), NOW)).toBe(weekly);
    expect(pickBrief(latest(null, null), NOW)).toBeNull();
  });
});

const done: TriggerAnalysisResult = { ok: true, status: "completed", outcome: "completed" };
const skipped: TriggerAnalysisResult = { ok: true, status: "skipped", outcome: "skipped" };
const disabled: TriggerAnalysisResult = { ok: false, error: "weekly_summary is disabled", outcome: "disabled" };
const failed = (error: string): TriggerAnalysisResult => ({ ok: false, error, outcome: "failed" });

describe("what the refresh button reports", () => {
  test("a skipped brief is not reported as refreshed", () => {
    expect(refreshNote(done, done, skipped)).toEqual({ kind: "message", text: "No new brief yet - there was nothing new to write." });
  });

  // The bug: any error whose text contained "disabled" read as "briefs are off".
  test("a failure whose text mentions 'disabled' is still a failure", () => {
    const note = refreshNote(done, done, failed("cloud provider disabled by consent"));
    expect(note).toEqual({ kind: "message", text: "Brief did not refresh: cloud provider disabled by consent" });
  });

  test("only the server's disabled answer means briefs are off", () => {
    expect(refreshNote(done, done, disabled)).toEqual({ kind: "briefs-off" });
  });

  test("a disabled supporting check is not a failed one", () => {
    expect(refreshNote(done, disabled, done)).toBeNull();
    expect(refreshNote(failed("timeout"), done, done)).toEqual({
      kind: "message",
      text: "Some checks did not finish. Try refreshing again.",
    });
  });

  test("the daily briefing is tried only when the weekly is disabled", () => {
    expect(needsDailyFallback(disabled)).toBe(true);
    expect(needsDailyFallback(failed("weekly is disabled?"))).toBe(false);
    expect(needsDailyFallback(skipped)).toBe(false);
  });
});
