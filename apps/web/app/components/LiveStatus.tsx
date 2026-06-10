"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

const POLL_MS = 30_000;

// Conditional poll against /api/changes (the Next proxy; key stays
// server-side). 304 = nothing new, costs a header exchange. A changed
// version_token re-renders the server components via router.refresh() — the
// dashboard updates close to real time without a reload. The mint dot only
// claims "live" while the poll is actually succeeding.
export function LiveStatus() {
  const router = useRouter();
  const etag = useRef<string | null>(null);
  const wasLive = useRef(false);
  const [state, setState] = useState<"unknown" | "live" | "offline">("unknown");

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
          wasLive.current = true;
          setState("live");
        } else if (res.status === 304) {
          wasLive.current = true;
          setState("live");
        } else {
          setState(wasLive.current ? "offline" : "unknown");
        }
      } catch {
        if (!stopped) setState(wasLive.current ? "offline" : "unknown");
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

  // Never claim "live" before the first successful poll — but once it HAS
  // been live, a silent disappearance isn't feedback: show offline instead.
  if (state === "unknown") return null;
  if (state === "offline") {
    return (
      <span className="pill mono live-pill offline" title="Live poll failing — backend unreachable">
        offline
      </span>
    );
  }
  return (
    <span className="pill mono live-pill" title="Watching for new data (30s poll)">
      <span className="live-dot" aria-hidden />
      live
    </span>
  );
}
