"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { liveAfterPoll, readCacheSignal } from "../lib/liveSignal";
import { type PollState, pollState, SIGNED_OUT_EVENT, signInPath } from "../lib/session";

const POLL_MS = 30_000;
// While cached values are being refreshed, look again soon so the redraw
// follows the refresh closely.
const UPDATING_POLL_MS = 2_000;

type LiveState = PollState | "updating";

const MINI_LABELS: Record<LiveState, { aria: string; title: string }> = {
  live: { aria: "Watching for new data", title: "Watching for new data (30s poll)" },
  updating: {
    aria: "Updating cached readings",
    title: "Some readings on this page are cached and being refreshed; the page redraws when they arrive",
  },
  offline: { aria: "Backend unreachable", title: "Backend unreachable" },
  "signed-out": { aria: "Signed out", title: "Signed out - sign in again to keep watching" },
  unknown: { aria: "Polling for first response", title: "Polling for first response" },
};

// Conditional poll against /api/changes (the Next proxy; key stays
// server-side). 304 = nothing new, costs a header exchange. A changed
// version_token re-renders the server components via router.refresh() - the
// dashboard updates close to real time without a reload. The mint dot only
// claims "live" while the poll is actually succeeding. A 401 means the web
// session ended: that is "signed out" with a way to sign in, not "offline".
export function LiveStatus({ renderedAt = 0 }: { renderedAt?: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const etag = useRef<string | null>(null);
  const wasLive = useRef(false);
  const [state, setState] = useState<LiveState>("unknown");
  // When the server rendered this page (server clock): a cache refresh that
  // landed later means the page may show older values, so it redraws.
  const renderedAtRef = useRef(renderedAt);
  useEffect(() => {
    renderedAtRef.current = Math.max(renderedAtRef.current, renderedAt);
  }, [renderedAt]);

  useEffect(() => {
    const signedOut = () => setState("signed-out");
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
  }, []);

  useEffect(() => {
    let stopped = false;
    let inflight = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = (ms: number) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(tick, ms);
    };
    const tick = async () => {
      if (inflight) return; // a hung poll must not race the next one
      inflight = true;
      let nextPoll = POLL_MS;
      try {
        const headers: Record<string, string> = {};
        if (etag.current) headers["If-None-Match"] = etag.current;
        const res = await fetch("/api/changes", { headers, cache: "no-store" });
        if (stopped) return;
        let refresh = false;
        if (res.status === 200) {
          const next = res.headers.get("etag");
          if (etag.current && next && next !== etag.current) refresh = true;
          if (next) etag.current = next;
        }
        let nextState: LiveState = pollState(res.status, wasLive.current);
        if (nextState === "live") {
          wasLive.current = true;
          // Cached values on this page being refreshed: say so, look again
          // soon, and redraw once the refresh has landed.
          const signal = readCacheSignal(res.headers);
          const { updating, redraw } = liveAfterPoll(signal, renderedAtRef.current);
          if (updating) {
            nextState = "updating";
            nextPoll = UPDATING_POLL_MS;
          }
          if (redraw && signal) {
            refresh = true;
            renderedAtRef.current = signal.settledAt;
          }
        }
        if (refresh) router.refresh();
        setState(nextState);
      } catch {
        if (!stopped) setState(pollState(null, wasLive.current));
      } finally {
        inflight = false;
        if (!stopped) schedule(nextPoll);
      }
    };
    tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [router]);

  // Never claim "live" before the first successful poll - but once it HAS
  // been live, a silent disappearance isn't feedback: show offline instead.
  // The mini indicator (used on mobile) renders in every state so phone users
  // always have a sync cue - it just changes color as the poll resolves.
  const miniOnly = (
    <span
      className={`live-mini${state === "offline" || state === "signed-out" ? " live-mini-offline" : ""}${
        state === "unknown" || state === "updating" ? " live-mini-pending" : ""
      }`}
      aria-label={MINI_LABELS[state].aria}
      title={MINI_LABELS[state].title}
    >
      <span className="live-dot" aria-hidden />
    </span>
  );
  if (state === "unknown") return miniOnly;
  if (state === "updating") {
    return (
      <>
        <span
          className="pill mono live-pill"
          title="Some readings on this page are cached and being refreshed; the page redraws when they arrive"
        >
          <span className="live-dot" aria-hidden />
          updating
        </span>
        {miniOnly}
      </>
    );
  }
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
