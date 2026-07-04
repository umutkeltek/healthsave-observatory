import type { CSSProperties } from "react";

import type { InsightsLatest, Narrative, NarratorRun, NarrativeHistoryItem } from "../lib/api";
import { briefParagraphs } from "../lib/textPresentation";
import { RefreshInsightsButton } from "./RefreshInsightsButton";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function hoursOld(iso: string | null): number | null {
  if (!iso) return null;
  return (Date.now() - new Date(iso).getTime()) / 3_600_000;
}

function lastNarratorRun(latest: InsightsLatest): NarratorRun | null {
  const candidates = [latest.runs?.weekly_summary, latest.runs?.daily_briefing].filter(
    (run): run is NarratorRun => Boolean(run),
  );
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));
  return candidates[0];
}

function RunStatusLine({ run }: { run: NarratorRun | null }) {
  if (!run) return null;

  if (run.status === "failed") {
    return (
      <p className="brief-run-status brief-run-failed">
        Refresh did not finish{run.at ? ` - ${formatDate(run.at)}` : ""}.{" "}
        <a href="/intelligence">Check Intelligence settings.</a>
      </p>
    );
  }

  if (run.status === "skipped") {
    return (
      <p className="brief-run-status">
        Brief paused{run.at ? ` - ${formatDate(run.at)}` : ""}. Add a little more history and try again.
      </p>
    );
  }

  return null;
}

function stripBriefLabel(text: string): string {
  return text.replace(/^(Recovery|Summary|Today|This week|Weekly brief):\s*/i, "").trim();
}

function splitBriefSentences(paragraphs: string[]): string[] {
  return paragraphs
    .flatMap((paragraph) => {
      const cleaned = stripBriefLabel(paragraph);
      return cleaned.split(/(?<=[.!?])\s+/);
    })
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function briefParts(brief: Narrative) {
  const paragraphs = briefParagraphs(brief.narrative);
  const sentences = splitBriefSentences(paragraphs);
  const lead = sentences[0] ?? paragraphs[0] ?? "Your recent data is ready to review.";
  const takeaways = sentences
    .slice(1)
    .filter((sentence) => sentence !== lead)
    .slice(0, 2);

  return {
    lead,
    takeaways,
    paragraphs,
  };
}

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
      <article className="card brief brief-clean">
        <h2>Weekly Brief</h2>
        <p className="empty">Could not load your brief. Check the sync app and refresh.</p>
      </article>
    );
  }

  // Prefer the weekly rollup; fall back to today's briefing until the week lands.
  const brief: Narrative | null = latest.weekly_summary ?? latest.daily_briefing;
  const lastRun = lastNarratorRun(latest);

  if (!brief) {
    return (
      <article className="card brief brief-clean">
        <div className="brief-head">
          <div>
            <h2>Weekly Brief</h2>
            <p className="brief-kicker">A short read appears here once enough data is synced.</p>
          </div>
          <RefreshInsightsButton />
        </div>

        <p className="empty">
          {narratorOff ? (
            <>
              Briefs are off. Your changes still appear in <strong>What changed</strong>.{" "}
              <a href="/intelligence">Turn on briefs</a>.
            </>
          ) : lastRun?.status === "failed" ? (
            "The last refresh did not finish."
          ) : (
            "No brief yet. Sync a few days of data, then refresh."
          )}
        </p>

        {!narratorOff && <RunStatusLine run={lastRun} />}
      </article>
    );
  }

  const scope = brief.insight_type === "weekly_summary" ? "This week" : "Today";
  const when = brief.created_at ? ` - ${formatDate(brief.created_at)}` : "";
  const age = hoursOld(brief.created_at);
  const staleAfter = brief.insight_type === "weekly_summary" ? 24 * 8 : 36;
  const stale = age !== null && age > staleAfter;
  const { lead, takeaways, paragraphs } = briefParts(brief);
  const previous = history.filter((item) => item.narrative !== brief.narrative).slice(0, 5);

  return (
    <article className="card brief brief-clean">
      <div className="brief-head">
        <div>
          <h2>Weekly Brief</h2>
          <p className="brief-kicker">
            {scope}
            {when} - saved locally
            {stale && <span className="brief-stale">Refresh suggested</span>}
          </p>
        </div>
        <RefreshInsightsButton />
      </div>

      {lastRun?.status === "failed" && brief.created_at !== null && (lastRun.at ?? "") > brief.created_at && (
        <RunStatusLine run={lastRun} />
      )}

      <section className="brief-main-read" aria-label="Main read">
        <span className="brief-label">Main read</span>
        <p className="anim-rise" style={{ "--i": 0 } as CSSProperties}>
          {lead}
        </p>
      </section>

      {takeaways.length > 0 && (
        <ul className="brief-takeaways" aria-label="Supporting points">
          {takeaways.map((takeaway) => (
            <li key={takeaway}>
              <span className="brief-dot" aria-hidden />
              <span>{takeaway}</span>
            </li>
          ))}
        </ul>
      )}

      {paragraphs.length > 0 && (
        <details className="brief-history brief-more">
          <summary>Read full brief</summary>
          <div className="brief-body">
            {paragraphs.map((paragraph, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: stable split of one narrative string.
              <p key={index}>{paragraph}</p>
            ))}
          </div>
        </details>
      )}

      {previous.length > 0 && (
        <details className="brief-history">
          <summary>Earlier briefs</summary>
          <ul>
            {previous.map((item) => (
              <li key={`${item.insight_type}-${item.created_at}`}>
                <span className="brief-history-meta mono">
                  {item.insight_type === "weekly_summary" ? "weekly" : "daily"} - {formatDate(item.created_at)}
                </span>
                <p>{briefParagraphs(item.narrative).join("\n\n")}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
