"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { LiveStatus } from "./LiveStatus";
import { ThemeToggle } from "./ThemeToggle";

const TITLES: Record<string, { title: string; sub: string }> = {
  "/": { title: "Today", sub: "Recovery, recent changes, and signals worth attention." },
  "/sleep": { title: "Sleep", sub: "Stages, duration, consistency, and sleep debt — night by night." },
  "/activity": { title: "Activity", sub: "Daily strain, steps, energy, and cardiovascular load." },
  "/demo": { title: "Today", sub: "A 30-day story using local demo data." },
  "/experiments": { title: "Experiments", sub: "Try a change, then measure whether it helped." },
  "/timeline": { title: "Timeline", sub: "Your health story at a glance — moments, changes, and decisions." },
  "/findings": { title: "Findings", sub: "Important changes first; calculations one layer deeper." },
  "/sources": { title: "Sources", sub: "Where each number came from and how fresh it is." },
  "/data": { title: "Data", sub: "Metrics, coverage, readiness, and export." },
  "/explore": { title: "Explore", sub: "Compose your own panels over any signals." },
  "/compare": { title: "Compare", sub: "Compare periods, sources, and devices without losing provenance." },
  "/relationships": { title: "Relationships", sub: "Explore how signals move together." },
  "/privacy": { title: "Privacy", sub: "What stayed local, what left this host, and why." },
  "/library": { title: "Library", sub: "Every signal you collect, searchable and pinnable." },
  "/intelligence": { title: "Intelligence", sub: "The narrator is local by default; cloud only by consent." },
  "/integrations": { title: "Integrations", sub: "Sources in, destinations out, with live posture." },
  "/settings": { title: "Settings", sub: "Preferences, services, and system state in one place." },
};

export function Topbar({
  status,
  onMenu,
}: {
  status: ReactNode;
  onMenu?: () => void;
}) {
  const pathname = usePathname();
  const segment = `/${pathname.split("/")[1] ?? ""}`;
  const { title, sub } = TITLES[pathname] ?? TITLES[segment] ?? TITLES["/"];

  return (
    <header className="topbar">
      <button type="button" className="menu-btn" onClick={onMenu} aria-label="Open navigation">
        <span />
        <span />
        <span />
      </button>
      <div className="topbar-title">
        <h1>{title}</h1>
        <p>{sub}</p>
      </div>
      <div className="topbar-status">
        <button
          type="button"
          className="palette-btn topbar-search"
          aria-label="Jump to a signal or page (Command K)"
          onClick={() => window.dispatchEvent(new Event("hs:palette"))}
        >
          <span>Search</span>
          <kbd className="palette-kbd">⌘K</kbd>
        </button>
        <div className="topbar-health" aria-label="Service status">
          <LiveStatus />
          {status}
        </div>
        <ThemeToggle />
      </div>
    </header>
  );
}
