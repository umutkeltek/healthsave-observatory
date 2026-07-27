"use client";

import { useState, useTransition } from "react";

import type { AnalyticalTimeSettings } from "../lib/api";
import { updateAnalyticalTimeAction } from "../lib/actions";

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

export function AnalyticalTimeSettingsForm({ initial }: { initial: AnalyticalTimeSettings }) {
  const [timeZone, setTimeZone] = useState(initial.time_zone);
  const [boundary, setBoundary] = useState(initial.day_boundary_minutes);
  const [pending, startTransition] = useTransition();
  const [status, setStatus] = useState<string | null>(null);
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
            const result = await updateAnalyticalTimeAction({
              time_zone: timeZone,
              day_boundary_minutes: boundary,
            });
            setStatus(result.ok ? "Saved. Calendar analyses now use this time basis." : (result.error ?? "Could not save."));
          })}
        >
          {pending ? "Saving…" : "Save time basis"}
        </button>
        {status && <span className={status.startsWith("Saved") ? "meta" : "exp-error"} role="status">{status}</span>}
      </div>
      <p className="meta">Current basis: {timeZone} · day boundary {boundaryLabel(boundary)}</p>
    </article>
  );
}
