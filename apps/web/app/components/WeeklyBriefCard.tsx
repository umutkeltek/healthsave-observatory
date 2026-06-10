import type { CSSProperties } from "react";

import type { InsightsLatest, Narrative, NarratorRun, NarrativeHistoryItem } from "../lib/api";
import { RefreshInsightsButton } from "./RefreshInsightsButton";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function hoursOld(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

// The most recent narrator attempt across both jobs. Optional-chained because
// a cached response from a pre-runs API revision has no `runs` key.
function lastNarratorRun(latest: InsightsLatest): NarratorRun | null {
  const candidates = [latest.runs?.weekly_summary, latest.runs?.daily_briefing].filter(
    (run): run is NarratorRun => Boolean(run),
  );
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));
  return candidates[0];
}

// One honest line about a non-completed last attempt. Failed runs name the
// error; skipped runs explain themselves; anything else stays quiet.
function RunStatusLine({ run }: { run: NarratorRun | null }) {
  if (!run) return null;
  if (run.status === "failed") {
    return (
      <p className="brief-run-status brief-run-failed">
        Last attempt failed{run.at ? ` · ${formatDate(run.at)}` : ""}
        {run.error ? `: ${run.error}` : ""}{" "}
        <a href="/intelligence">Check Intelligence settings.</a>
      </p>
    );
  }
  if (run.status === "skipped") {
    return (
      <p className="brief-run-status">
        Last run{run.at ? ` (${formatDate(run.at)})` : ""} was skipped — not enough data in the
        window yet.
      </p>
    );
  }
  return null;
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
  const lastRun = lastNarratorRun(latest);
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
          ) : lastRun?.status === "failed" ? (
            "The narrator is on, but the last attempt didn't produce a brief:"
          ) : (
            "No briefing yet — these are generated locally once you have a few days of data."
          )}
        </p>
        {!narratorOff && <RunStatusLine run={lastRun} />}
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
      {/* A failed attempt newer than the shown brief explains WHY it is stale. */}
      {lastRun?.status === "failed" &&
        brief.created_at !== null &&
        (lastRun.at ?? "") > brief.created_at && <RunStatusLine run={lastRun} />}
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
