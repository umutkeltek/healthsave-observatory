"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { afterPoll, armWatch, type LiveState, type PollMemory, readCacheSignal } from "../lib/liveSignal";
import type { Dictionary } from "../lib/i18n";
import { pollState, SIGNED_OUT_EVENT, signInPath } from "../lib/session";
import { useI18n } from "./I18nProvider";

export type { LiveState };

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
// A hidden tab does not poll; it polls at once when shown again. After a
// navigation it polls at once and then often for NAV_WATCH_MS, because the new
// page may be showing cached values that are being refreshed.
export function LiveStatus({ renderedSettled = 0 }: { renderedSettled?: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams()?.toString() ?? "";
  const { dict } = useI18n();
  // Between polls: the ETag, whether it has been live, the landed-refresh count
  // the shown page was rendered against (one landing later means the page may
  // show older values, so it redraws), and the fast-poll window. The decisions
  // live in lib/liveSignal.ts (afterPoll), where they are tested.
  const memory = useRef<PollMemory>({ etag: null, wasLive: false, renderedSettled, watchUntil: 0 });
  const pollNow = useRef<() => void>(() => {});
  const [state, setState] = useState<LiveState>("unknown");
  useEffect(() => {
    memory.current.renderedSettled = Math.max(memory.current.renderedSettled, renderedSettled);
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
    const hidden = () => document.visibilityState === "hidden";
    const schedule = (delay: number | null) => {
      if (timer) clearTimeout(timer);
      timer = delay === null ? null : setTimeout(tick, delay);
    };
    const tick = async () => {
      if (inflight) return; // a hung poll must not race the next one
      schedule(null);
      inflight = true;
      let delay: number | null = null;
      try {
        const headers: Record<string, string> = {};
        if (memory.current.etag) headers["If-None-Match"] = memory.current.etag;
        const res = await fetch("/api/changes", { headers, cache: "no-store" });
        if (stopped) return;
        const step = afterPoll(
          memory.current,
          { status: res.status, etag: res.headers.get("etag"), signal: readCacheSignal(res.headers) },
          performance.now(),
          hidden(),
        );
        memory.current = step.memory;
        delay = step.delay;
        if (step.refresh) router.refresh();
        setState(step.state);
      } catch {
        if (stopped) return;
        const step = afterPoll(memory.current, { status: null, etag: null, signal: null }, performance.now(), hidden());
        delay = step.delay;
        setState(pollState(null, memory.current.wasLive));
      } finally {
        inflight = false;
        if (!stopped) schedule(delay);
      }
    };
    pollNow.current = () => {
      if (!stopped && !hidden()) void tick();
    };
    // Hidden: stop; shown again: poll at once.
    const onVisibility = () => (hidden() ? schedule(null) : pollNow.current());
    document.addEventListener("visibilitychange", onVisibility);
    if (!hidden()) tick();
    return () => {
      stopped = true;
      pollNow.current = () => {};
      document.removeEventListener("visibilitychange", onVisibility);
      schedule(null);
    };
  }, [router]);

  // A navigation (path or URL state): the new page may show cached values
  // whose refresh is running or about to start, so look now and keep looking
  // often for a while. Only a navigation arms this; a redraw the poll causes
  // does not. Runs after the poll effect, so the first mount polls once.
  const firstRender = useRef(true);
  useEffect(() => {
    memory.current = armWatch(memory.current, performance.now());
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    pollNow.current();
  }, [pathname, search]);

  // Never claim "live" before the first successful poll - but once it HAS
  // been live, a silent disappearance isn't feedback: show offline instead.
  // The status dot (all phones keep) renders in every state.
  return <LivePill state={state} dict={dict} signInHref={signInPath(pathname ?? "/")} />;
}
