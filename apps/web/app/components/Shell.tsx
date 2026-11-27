"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import type { Density } from "../lib/prefs";
import { DensityProvider, useOptimisticDensity } from "./DensityToggle";
import { useI18n } from "./I18nProvider";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

// Client shell so the sidebar can become a slide-over drawer on small screens.
// On desktop it's a normal fixed sidebar; the menu button + scrim are CSS-hidden.
// Posture/sync status arrives as server-rendered slots (streamed via Suspense
// in the layout) so the chrome never blocks on backend reads.
export function Shell({
  sidebarStatus,
  participantSwitcher,
  topbarStatus,
  density,
  renderedSettled,
  children,
}: {
  sidebarStatus: ReactNode;
  participantSwitcher?: ReactNode;
  topbarStatus: ReactNode;
  density: Density;
  // Cache refreshes landed at render, for the live poll's redraw (LiveStatus).
  renderedSettled?: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [shownDensity, pickDensity] = useOptimisticDensity(density);
  const { dict } = useI18n();

  return (
    <DensityProvider value={{ density: shownDensity, pick: pickDensity }}>
      <div className={`app density-${shownDensity} ${open ? "nav-open" : ""}`}>
        <Sidebar
          status={sidebarStatus}
          participantSwitcher={participantSwitcher}
          density={shownDensity}
          onDensityChange={pickDensity}
          onNavigate={() => setOpen(false)}
        />
        <button
          type="button"
          className="nav-scrim"
          aria-label={dict.chrome.closeNavigation}
          hidden={!open}
          tabIndex={open ? 0 : -1}
          onClick={() => setOpen(false)}
        />
        <div className="app-main">
          <Topbar status={topbarStatus} renderedSettled={renderedSettled} onMenu={() => setOpen((v) => !v)} />
          <main className="content">{children}</main>
        </div>
      </div>
    </DensityProvider>
  );
}
