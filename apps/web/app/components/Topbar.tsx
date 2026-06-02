"use client";

import { usePathname } from "next/navigation";

const TITLES: Record<string, { title: string; sub: string }> = {
  "/": { title: "Overview", sub: "Your data, interpreted — not just charted." },
  "/experiments": { title: "Experiments", sub: "Run, measure, and act on what to try next." },
  "/evidence": { title: "Evidence", sub: "What the engine found — computed, not guessed." },
  "/data": { title: "Data", sub: "Coverage, freshness, and every metric." },
  "/privacy": { title: "Privacy", sub: "What leaves this host." },
};

export function Topbar({
  provider,
  isLocal,
  synced,
}: {
  provider: string;
  isLocal: boolean;
  synced: string;
}) {
  const pathname = usePathname();
  const { title, sub } = TITLES[pathname] ?? TITLES["/"];
  return (
    <header className="topbar">
      <div className="topbar-title">
        <h1>{title}</h1>
        <p>{sub}</p>
      </div>
      <div className="topbar-status">
        <span className="pill mono">
          {provider} · {isLocal ? "local" : "cloud"}
        </span>
        <span className="pill mono">synced {synced}</span>
      </div>
    </header>
  );
}
