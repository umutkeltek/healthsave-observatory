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
  const [live, setLive] = useState(false);

  useEffect(() => {
    let stopped = false;
    const tick = async () => {
      try {
        const headers: Record<string, string> = {};
        if (etag.current) headers["If-None-Match"] = etag.current;
        const res = await fetch("/api/changes", { headers, cache: "no-store" });
        if (stopped) return;
        if (res.status === 200) {
          const next = res.headers.get("etag");
          if (etag.current && next && next !== etag.current) router.refresh();
          if (next) etag.current = next;
          setLive(true);
        } else if (res.status === 304) {
          setLive(true);
        } else {
          setLive(false);
        }
      } catch {
        if (!stopped) setLive(false);
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, [router]);

  if (!live) return null;
  return (
    <span className="pill mono live-pill" title="Watching for new data (30s poll)">
      <span className="live-dot" aria-hidden />
      live
    </span>
  );
}
