"use client";

import type { ReactNode } from "react";
import { useState } from "react";

import type { PostureChip } from "../lib/load";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

// Client shell so the sidebar can become a slide-over drawer on small screens.
// On desktop it's a normal fixed sidebar; the menu button + scrim are CSS-hidden.
export function Shell({
  posture,
  synced,
  children,
}: {
  posture: PostureChip;
  synced: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className={`app ${open ? "nav-open" : ""}`}>
      <Sidebar posture={posture} synced={synced} onNavigate={() => setOpen(false)} />
      <button
        type="button"
        className="nav-scrim"
        aria-label="Close navigation"
        tabIndex={open ? 0 : -1}
        onClick={() => setOpen(false)}
      />
      <div className="app-main">
        <Topbar posture={posture} synced={synced} onMenu={() => setOpen((v) => !v)} />
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
