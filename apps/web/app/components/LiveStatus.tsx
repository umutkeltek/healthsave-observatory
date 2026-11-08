"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { liveAfterPoll, readCacheSignal } from "../lib/liveSignal";
import type { Dictionary } from "../lib/i18n";
import { type PollState, pollState, SIGNED_OUT_EVENT, signInPath } from "../lib/session";
import { useI18n } from "./I18nProvider";

const POLL_MS = 30_000;
// While cached values are being refreshed, look again soon so the redraw
// follows the refresh closely.
const UPDATING_POLL_MS = 2_000;

export type LiveState = PollState | "updating";

function labelsFor(dict: Dictionary, state: LiveState) {
  return dict.live[state === "signed-out" ? "signedOut" : state];
}

/**
 * The top-bar pill (and the status dot phones keep) for one state, in the
 * interface language. Pure, so every state renders and tests without polling.
 */
export function LivePill({ state, dict, signInHref }: { state: LiveState; dict: Dictionary; signInHref: string }) {
  const labels = labelsFor(dict, state);
  const mini = (
    <span
      className={`live-mini${state === "offline" || state === "signed-out" ? " live-mini-offline" : ""}${
        state === "unknown" || state === "updating" ? " live-mini-pending" : ""
      }`}
      aria-label={labels.aria}
      title={labels.title}
    >
      <span className="live-dot" aria-hidden />
    </span>
  );
  if (state === "unknown") return mini;
  const pill = dict.live[state === "signed-out" ? "signedOut" : state].pill;
  if (state === "signed-out") {
    // A new tab, so whatever is typed on this page survives signing in.
    return (
      <>
        <a className="pill mono live-pill offline" href={signInHref} target="_blank" rel="noopener" title={labels.title}>
          {pill}
        </a>
        {mini}
      </>
    );
  }
  return (
    <>
      <span className={`pill mono live-pill${state === "offline" ? " offline" : ""}`} title={labels.title}>
        {state === "offline" ? null : <span className="live-dot" aria-hidden />}
        {pill}
      </span>
      {mini}
    </>
  );
}


// Conditional poll against /api/changes (the Next proxy; key stays
// server-side). 304 = nothing new, costs a header exchange. A changed
// version_token re-renders the server components via router.refresh() - the
// dashboard updates close to real time without a reload. The mint dot only
// claims "live" while the poll is actually succeeding. A 401 means the web
// session ended: that is "signed out" with a way to sign in, not "offline".
export function LiveStatus({ renderedSettled = 0 }: { renderedSettled?: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const { dict } = useI18n();
  const etag = useRef<string | null>(null);
  const wasLive = useRef(false);
  const [state, setState] = useState<LiveState>("unknown");
  // How many cache refreshes had landed when the server rendered this page:
  // one landing later means the page may show older values, so it redraws.
  const renderedSettledRef = useRef(renderedSettled);
  useEffect(() => {
    renderedSettledRef.current = Math.max(renderedSettledRef.current, renderedSettled);
  }, [renderedSettled]);

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
          const { updating, redraw } = liveAfterPoll(signal, renderedSettledRef.current);
          if (updating) {
            nextState = "updating";
            nextPoll = UPDATING_POLL_MS;
          }
          if (redraw && signal) {
            refresh = true;
            renderedSettledRef.current = signal.settled;
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
  // The status dot (all phones keep) renders in every state.
  return <LivePill state={state} dict={dict} signInHref={signInPath(pathname ?? "/")} />;
}
