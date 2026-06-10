"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useState, useTransition } from "react";

import { setDensityAction } from "../lib/actions";
import type { Density } from "../lib/prefs";

const ICONS: Record<string, ReactNode> = {
  overview: (
    <>
      <rect x="2.5" y="2.5" width="4.5" height="4.5" rx="1" />
      <rect x="9" y="2.5" width="4.5" height="4.5" rx="1" />
      <rect x="2.5" y="9" width="4.5" height="4.5" rx="1" />
      <rect x="9" y="9" width="4.5" height="4.5" rx="1" />
    </>
  ),
  experiments: (
    <>
      <path d="M6 2.5h4" />
      <path d="M6.5 2.5v3.5L3.5 12a1.2 1.2 0 0 0 1.1 1.8h6.8A1.2 1.2 0 0 0 12.5 12L9.5 6V2.5" />
      <path d="M5.2 9.5h5.6" />
    </>
  ),
  findings: (
    <>
      <path d="M3 4h10" />
      <path d="M3 8h10" />
      <path d="M3 12h7" />
    </>
  ),
  sources: (
    <>
      <circle cx="4" cy="8" r="1.7" />
      <circle cx="12" cy="3.9" r="1.7" />
      <circle cx="12" cy="12.1" r="1.7" />
      <path d="M5.5 7.2 10.5 4.7" />
      <path d="M5.5 8.8 10.5 11.3" />
    </>
  ),
  data: (
    <>
      <ellipse cx="8" cy="4" rx="5" ry="2" />
      <path d="M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4" />
      <path d="M3 8c0 1.1 2.2 2 5 2s5-.9 5-2" />
    </>
  ),
  compare: (
    <>
      <path d="M2.5 5.5h8" />
      <path d="M8 3 10.5 5.5 8 8" />
      <path d="M13.5 10.5h-8" />
      <path d="M8 8 5.5 10.5 8 13" />
    </>
  ),
  privacy: <path d="M8 2.2l4.5 1.8v3.6c0 2.8-1.9 4.7-4.5 5.6-2.6-.9-4.5-2.8-4.5-5.6V4z" />,
  library: (
    <>
      <path d="M8 2.2 13.7 5.3 8 8.4 2.3 5.3z" />
      <path d="M2.3 8.4 8 11.5l5.7-3.1" />
      <path d="M2.3 11 8 14.1 13.7 11" />
    </>
  ),
  intelligence: (
    <>
      <path d="M8 1.8l1.5 3.2 3.2 1.5-3.2 1.5L8 11.2 6.5 8 3.3 6.5 6.5 5z" />
      <path d="M12.5 10.5l.6 1.3 1.3.6-1.3.6-.6 1.3-.6-1.3-1.3-.6 1.3-.6z" />
    </>
  ),
};

// `essential: true` rows show in both modes; the rest are Observatory-mode
// power surfaces (still URL-accessible in Essentials — only the nav slims).
const NAV = [
  { href: "/", label: "Today", icon: "overview", essential: true },
  { href: "/experiments", label: "Experiments", icon: "experiments", essential: false },
  { href: "/findings", label: "Findings", icon: "findings", essential: true },
  { href: "/sources", label: "Sources", icon: "sources", essential: false },
  { href: "/data", label: "Data", icon: "data", essential: false },
  { href: "/library", label: "Library", icon: "library", essential: true },
  { href: "/compare", label: "Compare", icon: "compare", essential: false },
  { href: "/privacy", label: "Privacy", icon: "privacy", essential: true },
  { href: "/intelligence", label: "Intelligence", icon: "intelligence", essential: false },
] as const;

// Optimistic: the nav reshapes the instant you click; the cookie write +
// server re-render settle in the background. Never disabled — switching back
// and forth must feel like a light switch, not a form submit.
function useOptimisticDensity(server: Density): [Density, (mode: Density) => void] {
  const [local, setLocal] = useState<Density | null>(null);
  const [, startTransition] = useTransition();
  const pick = (mode: Density) => {
    setLocal(mode);
    startTransition(() => setDensityAction(mode).then(() => undefined));
  };
  return [local ?? server, pick];
}

function DensityToggle({
  density,
  onPick,
}: {
  density: Density;
  onPick: (mode: Density) => void;
}) {
  return (
    <div className="density-toggle" role="group" aria-label="View mode">
      <button
        type="button"
        className={density === "essentials" ? "active" : ""}
        onClick={() => onPick("essentials")}
      >
        Essentials
      </button>
      <button
        type="button"
        className={density === "observatory" ? "active" : ""}
        onClick={() => onPick("observatory")}
      >
        Observatory
      </button>
    </div>
  );
}

function NavIcon({ name }: { name: string }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {ICONS[name]}
    </svg>
  );
}

export function Sidebar({
  status,
  density,
  onNavigate,
}: {
  status: ReactNode;
  density: Density;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const [shownDensity, pickDensity] = useOptimisticDensity(density);
  const items = shownDensity === "essentials" ? NAV.filter((item) => item.essential) : NAV;
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden>
          ◆
        </span>
        <span className="brand-name">HealthSave</span>
        <span className="brand-sub">Observatory</span>
      </div>

      <nav className="nav">
        {items.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-item ${active ? "active" : ""}`}
              onClick={onNavigate}
            >
              <NavIcon name={item.icon} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="sidebar-foot">
        <DensityToggle density={shownDensity} onPick={pickDensity} />
        {status}
      </div>
    </aside>
  );
}
