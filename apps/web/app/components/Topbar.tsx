"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { ThemeToggle } from "./ThemeToggle";

const TITLES: Record<string, { title: string; sub: string }> = {
  "/": { title: "Today", sub: "Your body, interpreted — with proof." },
  "/demo": { title: "Today", sub: "A believable 30-day story — demo data." },
  "/experiments": { title: "Experiments", sub: "Run, measure, and act on what to try next." },
  "/findings": { title: "Findings", sub: "What the engine found — computed, not guessed." },
  "/sources": { title: "Sources", sub: "Where your data comes from — origin and freshness." },
  "/data": { title: "Data", sub: "Coverage, freshness, and every metric." },
  "/compare": { title: "Compare", sub: "Period vs previous, source vs source — both kept." },
  "/privacy": { title: "Privacy", sub: "What leaves this host." },
};

export function Topbar({
  status,
  onMenu,
}: {
  status: ReactNode;
  onMenu?: () => void;
}) {
  const pathname = usePathname();
  const { title, sub } = TITLES[pathname] ?? TITLES["/"];
  return (
    <header className="topbar">
      <button type="button" className="menu-btn" onClick={onMenu} aria-label="Open navigation">
        <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden>
          <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />
        </svg>
      </button>
      <div className="topbar-title">
        <h1>{title}</h1>
        <p>{sub}</p>
      </div>
      <div className="topbar-status">
        {status}
        <ThemeToggle />
      </div>
    </header>
  );
}
