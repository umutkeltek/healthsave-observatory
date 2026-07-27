import type { Finding, Moment } from "../lib/api";
import { agoLabel } from "../lib/load";

const KIND_ICON: Record<string, string> = {
  illness: "🤒",
  alcohol: "🍷",
  late_meal: "🍽",
  travel: "✈",
  medication_change: "💊",
  supplement_change: "💊",
  hard_training: "🏋",
  stress: "😰",
  caffeine: "☕",
  injury: "🤕",
  menstrual: "🩸",
  custom: "📌",
};

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
  const claim =
    typeof finding.structured_data?.claim === "string"
      ? finding.structured_data.claim
      : null;
  return claim ?? `${finding.finding_type} · ${finding.metric ?? ""}`;
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
                    <span className="timeline-icon" aria-hidden>
                      {KIND_ICON[moment.kind] ?? "📌"}
                    </span>
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
                  <span className="timeline-icon" aria-hidden>
                    🔍
                  </span>
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
