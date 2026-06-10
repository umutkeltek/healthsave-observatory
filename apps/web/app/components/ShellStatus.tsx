// Async server components for the chrome's posture/sync status. The layout
// streams these inside Suspense so the shell paints immediately instead of
// waiting on the privacy + readiness reads (the old first-byte waterfall).
// Fallbacks assert only what we can't get wrong ("on-host", no sync claim) —
// the same posture postureChip reports when the backend is unreachable.

import { agoLabel, postureChip, safePrivacy, safeReadiness } from "../lib/load";

async function loadStatus() {
  const [privacy, readiness] = await Promise.all([safePrivacy(), safeReadiness()]);
  return {
    posture: postureChip(privacy),
    synced: agoLabel(readiness?.last_ingested_at ?? readiness?.last_observation_at ?? null),
  };
}

export async function SidebarStatus() {
  const { posture, synced } = await loadStatus();
  return (
    <>
      <div className="status-line">
        <span className={`status-dot ${posture.ok ? "" : "warn"}`} />
        {posture.text}
      </div>
      <div className="status-sub">synced {synced}</div>
    </>
  );
}

export function SidebarStatusFallback() {
  return (
    <>
      <div className="status-line">
        <span className="status-dot" />
        on-host
      </div>
      <div className="status-sub">synced …</div>
    </>
  );
}

export async function TopbarStatus() {
  const { posture, synced } = await loadStatus();
  return (
    <>
      <span className="pill mono">{posture.text}</span>
      <span className="pill mono">synced {synced}</span>
    </>
  );
}

export function TopbarStatusFallback() {
  return (
    <>
      <span className="pill mono">on-host</span>
      <span className="pill mono">synced …</span>
    </>
  );
}
