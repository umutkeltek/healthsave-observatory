import type { CSSProperties } from "react";

import type { InsightsLatest, Narrative, NarrativeHistoryItem } from "../lib/api";
import { RefreshInsightsButton } from "./RefreshInsightsButton";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function hoursOld(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

// Four honest states: unreachable / narrator off / no brief yet / brief
// (fresh or stale). Paragraphs stagger in via the rise keyframe — the honest
// alternative to a fake typewriter on a non-streaming narrator.
export function WeeklyBriefCard({
  latest,
  narratorOff = false,
  history = [],
}: {
  latest: InsightsLatest | null;
  narratorOff?: boolean;
  history?: NarrativeHistoryItem[];
}) {
  if (!latest) {
    return (
      <article className="card brief">
        <h2>Weekly Brief</h2>
        <p className="empty">Backend unreachable — start HealthSave Observatory and sync from the app.</p>
      </article>
    );
  }

  // Prefer the weekly rollup; fall back to today's briefing until a week lands.
  const brief: Narrative | null = latest.weekly_summary ?? latest.daily_briefing;
  if (!brief) {
    return (
      <article className="card brief">
        <div className="brief-head">
          <h2>Weekly Brief</h2>
          <RefreshInsightsButton />
        </div>
        <p className="empty">
          {narratorOff ? (
            <>
              Narration is off — your numbers still tell the story in the evidence feed.{" "}
              <a href="/intelligence">Turn it on under Intelligence.</a>
            </>
          ) : (
            "No briefing yet — these are generated locally once you have a few days of data."
          )}
        </p>
      </article>
    );
  }

  const scope = brief.insight_type === "weekly_summary" ? "This week" : "Today";
  const when = brief.created_at ? ` · ${formatDate(brief.created_at)}` : "";
  const age = hoursOld(brief.created_at);
  const staleAfter = brief.insight_type === "weekly_summary" ? 24 * 8 : 36;
  const stale = age !== null && age > staleAfter;
  const paragraphs = brief.narrative
    .split(/\n{2,}|\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  const previous = history.filter((item) => item.narrative !== brief.narrative).slice(0, 5);

  return (
    <article className="card brief">
      <div className="brief-head">
        <h2>Weekly Brief</h2>
        <RefreshInsightsButton />
      </div>
      <div className="brief-meta">
        {scope}
        {when} · interpreted locally
        {stale && <span className="brief-stale">stale</span>}
      </div>
      <div className="brief-body">
        {paragraphs.map((paragraph, index) => (
          // Index keys are correct here: the list is a stable split of one
          // string per render and never reorders. Content-prefix keys would
          // collide when the narrator repeats an opener.
          // biome-ignore lint: see above
          <p key={index} className="anim-rise" style={{ "--i": index } as CSSProperties}>
            {paragraph}
          </p>
        ))}
      </div>
      {previous.length > 0 && (
        <details className="brief-history">
          <summary>Previous briefs</summary>
          <ul>
            {previous.map((item) => (
              <li key={`${item.insight_type}-${item.created_at}`}>
                <span className="brief-history-meta mono">
                  {item.insight_type === "weekly_summary" ? "weekly" : "daily"} ·{" "}
                  {formatDate(item.created_at)}
                </span>
                <p>{item.narrative}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
