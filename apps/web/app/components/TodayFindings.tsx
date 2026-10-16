import Link from "next/link";
import type { Finding } from "../lib/api";
import {
  findingGroupId,
  userFindingSummary,
  userFindingTitle,
} from "../lib/findingPresentation";
import { formatAgo } from "../lib/format";
import { todayFindings } from "../lib/todayPresentation";

export function TodayFindings({ findings }: { findings: Finding[] | null }) {
  const selected = todayFindings(findings ?? []);
  return (
    <article className="card today-findings">
      <div className="today-section-heading">
        <h2>Worth a closer look</h2>
        <Link href="/findings">
          All findings <span aria-hidden>↗</span>
        </Link>
      </div>
      {selected.length > 0 ? (
        <ul className="today-finding-list">
          {selected.map((finding) => (
            <li key={finding.id}>
              <span
                className={`today-finding-mark finding-${findingGroupId(finding)}`}
                aria-hidden
              />
              <div>
                <h3>{userFindingTitle(finding)}</h3>
                <p>{userFindingSummary(finding)}</p>
                <span className="today-finding-time">
                  {formatAgo(finding.created_at)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty">
          {findings === null
            ? "Findings could not load. Try again shortly."
            : "No new changes to highlight. Your readings will help build a clearer picture."}
        </p>
      )}
      <Link className="today-evidence-link" href="/findings">
        View findings and evidence <span aria-hidden>→</span>
      </Link>
    </article>
  );
}
