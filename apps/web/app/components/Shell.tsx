"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

// Client shell so the sidebar can become a slide-over drawer on small screens.
// On desktop it's a normal fixed sidebar; the menu button + scrim are CSS-hidden.
// Posture/sync status arrives as server-rendered slots (streamed via Suspense
// in the layout) so the chrome never blocks on backend reads.
export function Shell({
  sidebarStatus,
  topbarStatus,
  children,
}: {
  sidebarStatus: ReactNode;
  topbarStatus: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`app ${open ? "nav-open" : ""}`}>
      <Sidebar status={sidebarStatus} onNavigate={() => setOpen(false)} />
      <button
        type="button"
        className="nav-scrim"
        aria-label="Close navigation"
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
