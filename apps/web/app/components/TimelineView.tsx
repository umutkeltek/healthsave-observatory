import type { ReactNode } from "react";

import type { Finding, Moment } from "../lib/api";
import { agoLabel } from "../lib/load";

// Thin-stroke inline glyphs (16×16, matching the Sidebar icon grammar) instead
// of colour emoji, which rendered inconsistently across platforms and broke the
// icon vocabulary. Each entry is the inner content of the <svg> in KindIcon.
const KIND_ICON: Record<string, ReactNode> = {
  illness: (
    <>
      <circle cx="8" cy="8" r="5.3" />
      <path d="M8 5.4v5.2M5.4 8h5.2" />
    </>
  ),
  alcohol: (
    <>
      <path d="M3.5 4h9l-4.5 5v3.2" />
      <path d="M5.7 13.2h4.6" />
    </>
  ),
  late_meal: (
    <>
      <path d="M6 3v3a1.6 1.6 0 0 0 3.2 0V3" />
      <path d="M7.6 6.6V13" />
      <path d="M11.5 3v10" />
    </>
  ),
  travel: (
    <>
      <path d="M14 2.5 2.5 7l4 1.7L8.5 13z" />
      <path d="M6.5 8.7 14 2.5" />
    </>
  ),
  medication_change: (
    <>
      <rect x="2.6" y="6" width="10.8" height="4" rx="2" />
      <path d="M8 6v4" />
    </>
  ),
  supplement_change: (
    <>
      <path d="M3.5 12.5c0-4.5 3.5-7.5 9-7.5 0 5-3.5 7.5-9 7.5z" />
      <path d="M5.8 10.2C7.6 8.4 9.4 7.3 11.5 7" />
    </>
  ),
  hard_training: (
    <>
      <path d="M3.5 8h9" />
      <path d="M2.2 6.4v3.2M13.8 6.4v3.2" />
      <path d="M2.9 5.8v4.4M13.1 5.8v4.4" />
    </>
  ),
  stress: <path d="M9 2 5 8.5h2.6L6.6 14l4.4-6.4H8.4z" />,
  caffeine: (
    <>
      <path d="M4 6h6v2.4a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3z" />
      <path d="M10 7h1.6a1.5 1.5 0 0 1 0 3H10" />
      <path d="M5.4 3v1.2M7.6 3v1.2" />
    </>
  ),
  injury: (
    <>
      <rect x="3" y="6.5" width="10" height="3" rx="1.5" />
      <path d="M5.3 8h1.4M9.3 8h1.4" />
    </>
  ),
  menstrual: <path d="M8 2.5c2.6 2.8 3.6 4.7 3.6 6.4a3.6 3.6 0 1 1-7.2 0c0-1.7 1-3.6 3.6-6.4z" />,
  custom: (
    <>
      <path d="M3.5 3.5h4.4l5.1 5.1-4.4 4.4-5.1-5.1z" />
      <circle cx="6" cy="6" r="0.9" />
    </>
  ),
};

function KindIcon({ name }: { name: string }) {
  return (
    <span className="timeline-icon" aria-hidden>
      <svg
        className="timeline-kind-icon"
        viewBox="0 0 16 16"
        width="16"
        height="16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {KIND_ICON[name] ?? KIND_ICON.custom}
      </svg>
    </span>
  );
}

// Findings get a magnifier rather than a moment-kind glyph.
function FindingIcon() {
  return (
    <span className="timeline-icon" aria-hidden>
      <svg
        className="timeline-kind-icon"
        viewBox="0 0 16 16"
        width="16"
        height="16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="6.6" cy="6.6" r="3.4" />
        <path d="M9.2 9.2 13 13" />
      </svg>
    </span>
  );
}

function fmtGrade(grade: string | null): string {
  if (!grade) return "";
  return grade === "mild" ? " · mild" : grade === "moderate" ? " · moderate" : " · severe";
}

type TimelineEvent =
  | { kind: "moment"; at: string; moment: Moment }
  | { kind: "finding"; at: string; finding: Finding };

function eventsFrom(moments: Moment[], findings: Finding[]): TimelineEvent[] {
  const list: TimelineEvent[] = [];
  for (const moment of moments) {
    list.push({ kind: "moment", at: moment.start_at, moment });
  }
  for (const finding of findings) {
    if (finding.created_at) {
      list.push({ kind: "finding", at: finding.created_at, finding });
    }
  }
  list.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
  return list;
}

function findingTitle(finding: Finding): string {
  // Prefer the typed FindingCard schema, fall back to legacy
  // ``structured_data.claim``, finally to a type/metric breadcrumb.
  if (finding.card?.claim) return finding.card.claim;
  const legacyClaim =
    typeof finding.structured_data?.claim === "string"
      ? finding.structured_data.claim
      : null;
  return legacyClaim ?? `${finding.finding_type ?? "finding"} · ${finding.metric ?? ""}`;
}

export function TimelineView({
  moments,
  findings,
}: {
  moments: Moment[];
  findings: Finding[];
}) {
  const events = eventsFrom(moments, findings);

  return (
    <article className="card">
      {events.length === 0 ? (
        <p className="empty">
          No moments or findings yet. Add a moment to build your personal timeline.
        </p>
      ) : (
        <div className="timeline-scroll">
          <ul className="timeline">
            {events.map((event, index) => {
              const key = `${event.kind}-${index}`;
              if (event.kind === "moment") {
                const moment = event.moment;
                return (
                  <li key={key} className="timeline-item timeline-moment">
                    <KindIcon name={moment.kind} />
                    <div>
                      <strong>{moment.title}</strong>
                      {fmtGrade(moment.grade)}
                      {moment.note && (
                        <p className="meta">{moment.note}</p>
                      )}
                      {moment.created_at && (
                        <span className="mono timeline-date">{agoLabel(moment.created_at)}</span>
                      )}
                    </div>
                  </li>
                );
              }
              const finding = event.finding;
              return (
                <li key={key} className="timeline-item timeline-finding">
                  <FindingIcon />
                  <div>
                    <strong>{findingTitle(finding)}</strong>
                    <span className="mono timeline-date">{agoLabel(finding.created_at!)}</span>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </article>
  );
}
