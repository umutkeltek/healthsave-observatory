import type { InsightsLatest, Narrative } from "../lib/api";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function WeeklyBriefCard({ latest }: { latest: InsightsLatest | null }) {
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
        <h2>Weekly Brief</h2>
        <p className="empty">
          No briefing yet — these are generated locally once you have a few days of data.
        </p>
      </article>
    );
  }

  const scope = brief.insight_type === "weekly_summary" ? "This week" : "Today";
  const when = brief.created_at ? ` · ${formatDate(brief.created_at)}` : "";

  return (
    <article className="card brief">
      <h2>Weekly Brief</h2>
      <div className="brief-meta">
        {scope}
        {when} · interpreted locally
      </div>
      <p className="brief-body">{brief.narrative}</p>
    </article>
  );
}
