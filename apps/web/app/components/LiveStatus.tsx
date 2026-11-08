"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { type PollState, pollState, SIGNED_OUT_EVENT, signInPath } from "../lib/session";

const POLL_MS = 30_000;

// Conditional poll against /api/changes (the Next proxy; key stays
// server-side). 304 = nothing new, costs a header exchange. A changed
// version_token re-renders the server components via router.refresh() - the
// dashboard updates close to real time without a reload. The mint dot only
// claims "live" while the poll is actually succeeding. A 401 means the web
// session ended: that is "signed out" with a way to sign in, not "offline".
export function LiveStatus() {
  const router = useRouter();
  const pathname = usePathname();
  const etag = useRef<string | null>(null);
  const wasLive = useRef(false);
  const [state, setState] = useState<PollState>("unknown");

  useEffect(() => {
    const signedOut = () => setState("signed-out");
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
  }, []);

  useEffect(() => {
    let stopped = false;
    let inflight = false;
    const tick = async () => {
      if (inflight) return; // a hung poll must not race the next interval
      inflight = true;
      try {
        const headers: Record<string, string> = {};
        if (etag.current) headers["If-None-Match"] = etag.current;
        const res = await fetch("/api/changes", { headers, cache: "no-store" });
        if (stopped) return;
        if (res.status === 200) {
          const next = res.headers.get("etag");
          if (etag.current && next && next !== etag.current) router.refresh();
          if (next) etag.current = next;
        }
        const nextState = pollState(res.status, wasLive.current);
        if (nextState === "live") wasLive.current = true;
        setState(nextState);
      } catch {
        if (!stopped) setState(pollState(null, wasLive.current));
      } finally {
        inflight = false;
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, [router]);

  // Never claim "live" before the first successful poll - but once it HAS
  // been live, a silent disappearance isn't feedback: show offline instead.
  // The mini indicator (used on mobile) renders in every state so phone users
  // always have a sync cue - it just changes color as the poll resolves.
  const miniOnly = (
    <span
      className={`live-mini${state === "offline" || state === "signed-out" ? " live-mini-offline" : ""}${
        state === "unknown" ? " live-mini-pending" : ""
      }`}
      aria-label={
        state === "live"
          ? "Watching for new data"
          : state === "offline"
            ? "Backend unreachable"
            : state === "signed-out"
              ? "Signed out"
              : "Polling for first response"
      }
      title={
        state === "live"
          ? "Watching for new data (30s poll)"
          : state === "offline"
            ? "Backend unreachable"
            : state === "signed-out"
              ? "Signed out - sign in again to keep watching"
              : "Polling for first response"
      }
    >
      <span className="live-dot" aria-hidden />
    </span>
  );
  if (state === "unknown") return miniOnly;
  if (state === "signed-out") {
    // A new tab, so whatever is typed on this page survives signing in.
    return (
      <>
        <a
          className="pill mono live-pill offline"
          href={signInPath(pathname ?? "/")}
          target="_blank"
          rel="noopener"
          title="Your session ended. Sign in again in a new tab, then come back to this one."
        >
          signed out · sign in
        </a>
        {miniOnly}
      </>
    );
  }
  if (state === "offline") {
    return (
      <>
        <span className="pill mono live-pill offline" title="Live poll failing - backend unreachable">
          offline
        </span>
        {miniOnly}
      </>
    );
  }
  return (
    <>
      <span className="pill mono live-pill" title="Watching for new data (30s poll)">
        <span className="live-dot" aria-hidden />
        live
      </span>
      {miniOnly}
    </>
  );
}
