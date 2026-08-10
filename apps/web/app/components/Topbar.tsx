"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { LiveStatus } from "./LiveStatus";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { ThemeToggle } from "./ThemeToggle";
import { useI18n } from "./I18nProvider";

const TITLE_KEYS = {
  "/": ["today", "todaySub"],
  "/sleep": ["sleep", "sleepSub"],
  "/activity": ["activity", "activitySub"],
  "/demo": ["today", "demoSub"],
  "/experiments": ["experiments", "experimentsSub"],
  "/timeline": ["timeline", "timelineSub"],
  "/findings": ["findings", "findingsSub"],
  "/sources": ["sources", "sourcesSub"],
  "/data": ["data", "dataSub"],
  "/explore": ["explore", "exploreSub"],
  "/compare": ["compare", "compareSub"],
  "/relationships": ["relationships", "relationshipsSub"],
  "/privacy": ["privacy", "privacySub"],
  "/library": ["library", "librarySub"],
  "/intelligence": ["intelligence", "intelligenceSub"],
  "/integrations": ["integrations", "integrationsSub"],
  "/settings": ["settings", "settingsSub"],
} as const;

export function Topbar({
  status,
  onMenu,
}: {
  status: ReactNode;
  onMenu?: () => void;
}) {
  const pathname = usePathname();
  const segment = `/${pathname.split("/")[1] ?? ""}`;
  const { dict } = useI18n();
  const [titleKey, subKey] = TITLE_KEYS[pathname as keyof typeof TITLE_KEYS] ??
    TITLE_KEYS[segment as keyof typeof TITLE_KEYS] ??
    TITLE_KEYS["/"];
  const title = dict.titles[titleKey];
  const sub = dict.titles[subKey];

  return (
    <header className="topbar">
      <button type="button" className="menu-btn" onClick={onMenu} aria-label={dict.chrome.openNavigation}>
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
          aria-label={dict.chrome.commandSearch}
          onClick={() => window.dispatchEvent(new Event("hs:palette"))}
        >
          <span>{dict.chrome.search}</span>
          <kbd className="palette-kbd">⌘K</kbd>
        </button>
        <LanguageSwitcher compact />
        <div className="topbar-health" aria-label={dict.chrome.serviceStatus}>
          <LiveStatus />
          {status}
        </div>
        <ThemeToggle />
      </div>
    </header>
  );
}
