"use client";

import { useState, useTransition } from "react";

import type { AnalyticalTimeSettings } from "../lib/api";
import { updateAnalyticalTimeAction } from "../lib/actions";
import { runAction } from "../lib/session";

const COMMON_ZONES = [
  "UTC",
  "Europe/Istanbul",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Australia/Sydney",
];

function boundaryLabel(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}`;
}

type Basis = Pick<AnalyticalTimeSettings, "time_zone" | "day_boundary_minutes">;

function basisLabel(basis: Basis): string {
  return `${basis.time_zone} · day boundary ${boundaryLabel(basis.day_boundary_minutes)}`;
}

// The saved basis (from the server) is what analyses use; the form's draft is
// only that until it is saved.
export function TimeBasisSummary({ saved, draft }: { saved: Basis; draft: Basis }) {
  const unsaved = draft.time_zone !== saved.time_zone || draft.day_boundary_minutes !== saved.day_boundary_minutes;
  return (
    <>
      <p className="meta">Current basis: {basisLabel(saved)}</p>
      {unsaved && <p className="meta">Not saved yet: {basisLabel(draft)}</p>}
    </>
  );
}

export type TimeBasisSaveStatus = { kind: "saved" } | { kind: "error"; message: string };

export function TimeBasisStatus({ status }: { status: TimeBasisSaveStatus | null }) {
  if (!status) return null;
  return status.kind === "saved" ? (
    <span className="meta" role="status">
      Saved. Calendar analyses now use this time basis.
    </span>
  ) : (
    <span className="exp-error" role="status">
      {status.message}
    </span>
  );
}

export function AnalyticalTimeSettingsForm({ initial }: { initial: AnalyticalTimeSettings }) {
  const [timeZone, setTimeZone] = useState(initial.time_zone);
  const [boundary, setBoundary] = useState(initial.day_boundary_minutes);
  const [pending, startTransition] = useTransition();
  const [status, setStatus] = useState<TimeBasisSaveStatus | null>(null);
  const zones = COMMON_ZONES.includes(timeZone) ? COMMON_ZONES : [timeZone, ...COMMON_ZONES];

  return (
    <article className="card">
      <h2>Analytical day</h2>
      <p className="set-hint">
        Calendar charts use your local time. Readings before the boundary stay with the previous
        physiological day; sleep is assigned by wake time. Absolute source timestamps are never changed.
      </p>
      <div className="field-grid">
        <label className="field-label">
          Time zone
          <select className="field-input" value={timeZone} onChange={(event) => setTimeZone(event.target.value)}>
            {zones.map((zone) => (
              <option value={zone} key={zone}>{zone}</option>
            ))}
          </select>
        </label>
        <label className="field-label">
          Day starts at
          <select
            className="field-input"
            value={boundary}
            onChange={(event) => setBoundary(Number(event.target.value))}
          >
            {[0, 120, 180, 240, 270, 300, 360, 480, 720].map((minutes) => (
              <option value={minutes} key={minutes}>{boundaryLabel(minutes)}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="exp-action">
        <button
          className="btn"
          type="button"
          disabled={pending}
          onClick={() => startTransition(async () => {
            const result = await runAction(() =>
              updateAnalyticalTimeAction({
                time_zone: timeZone,
                day_boundary_minutes: boundary,
              }),
            );
            setStatus(result.ok ? { kind: "saved" } : { kind: "error", message: result.error ?? "Could not save." });
          })}
        >
          {pending ? "Saving…" : "Save time basis"}
        </button>
        <TimeBasisStatus status={status} />
      </div>
      <TimeBasisSummary saved={initial} draft={{ time_zone: timeZone, day_boundary_minutes: boundary }} />
    </article>
  );
}
