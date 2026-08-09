"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import type { Density } from "../lib/prefs";
import { useOptimisticDensity } from "./DensityToggle";
import { useI18n } from "./I18nProvider";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

// Client shell so the sidebar can become a slide-over drawer on small screens.
// On desktop it's a normal fixed sidebar; the menu button + scrim are CSS-hidden.
// Posture/sync status arrives as server-rendered slots (streamed via Suspense
// in the layout) so the chrome never blocks on backend reads.
export function Shell({
  sidebarStatus,
  topbarStatus,
  density,
  children,
}: {
  sidebarStatus: ReactNode;
  topbarStatus: ReactNode;
  density: Density;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [shownDensity, pickDensity] = useOptimisticDensity(density);
  const { dict } = useI18n();

  return (
    <div className={`app density-${shownDensity} ${open ? "nav-open" : ""}`}>
      <Sidebar
        status={sidebarStatus}
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
        <Topbar status={topbarStatus} onMenu={() => setOpen((v) => !v)} />
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
